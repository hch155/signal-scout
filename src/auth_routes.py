"""Auth-related routes split out of app.py as a Flask blueprint.

Scope: register / login / logout / session_check / account / regenerate_api_key.
Stations / find / search / submit_location stay in app.py for now (their
move is more delicate because of the /api/v1/ aliases — done in a follow-up).

Why blueprint
- app.py was 530+ lines doing routing + security headers + CSRF + auth +
  data + page rendering. Auth is the most self-contained slice — extract
  it first as the pattern proof, then peel the rest.
- Each blueprint can later get a `url_prefix='/tenants/<tenant_id>'` for
  multi-tenant without touching every route handler.

Caveat: this blueprint imports the global `bcrypt`, `db`, `limiter`,
`validate_csrf`, observability counters, and `generate_api_key` from app.py.
That circular-ish import works because Flask blueprints register lazily —
the blueprint object is defined here, the app pulls it in via init_app().
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, session

from models import User, ApiKey, AuditEvent, UserLocation, UserStationSnapshot
from kms import get_kms
from api_access import hash_api_key, format_api_key_prefix
from observability import (
    funnel_register_started_total,
    funnel_register_completed_total,
    funnel_first_api_key_created_total,
)


logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


_deps: dict = {}


def _bcrypt():
    return _deps["bcrypt"]


def _db():
    return _deps["db"]


def _limiter():
    return _deps["limiter"]


def _validate_csrf():
    return _deps["validate_csrf"]()


def _generate_api_key():
    return _deps["generate_api_key"]()


def _csrf_failures_total():
    return _deps["csrf_failures_total"]


def _login_failures_total():
    return _deps["login_failures_total"]


def _email_rate_component() -> str:
    try:
        from flask import request
        email = (request.form.get('email')
                 or (request.get_json(silent=True) or {}).get('email')
                 or '')
        email = _normalize_email(email.strip()) if email else ''
        if not email:
            return 'noemail'
        import hashlib
        return hashlib.sha256(email.encode('utf-8')).hexdigest()[:16]
    except Exception:
        return 'noemail'


def _login_rate_key() -> str:
    from flask_limiter.util import get_remote_address
    return f"{get_remote_address()}|{_email_rate_component()}"


def _register_rate_key() -> str:
    from flask_limiter.util import get_remote_address
    return f"{get_remote_address()}|{_email_rate_component()}"


def _forgot_password_rate_key() -> str:
    from flask_limiter.util import get_remote_address
    return f"{get_remote_address()}|{_email_rate_component()}"


LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = timedelta(minutes=15)

_DUMMY_BCRYPT_HASH = (
    '$2b$12$wFRtPM8VvZdEdBbY5lJ4ZeEf4eXIYlD0d1yhxwOO5Z3cV1Mv8qC.O'
)


def _is_locked(user) -> bool:
    """Audit fix (High — lockout bypass): originally only login_user
    consulted user.locked_until. That meant a brute-forcer could
    trigger a lock via /login, then immediately resume bcrypt-checking
    the password through /account/password (the change_password handler
    requires the current password to be passed in). Same shape on
    /account/2fa/disable (recovery code accepted), /account/delete
    (password required), /account/2fa/regenerate (password required).
    Each of these is now gated by this helper."""
    return bool(
        user is not None
        and user.locked_until is not None
        and user.locked_until > datetime.utcnow()
    )


def _record_failed_password_attempt(user, *, endpoint: str) -> None:
    """Atomically bump user.failed_login_attempts and lock if past
    threshold.

    Companion to _is_locked: every endpoint that runs
    bcrypt.check_password_hash on user-supplied input must call this on
    the failure branch so the same five-attempts-per-15-minutes ceiling
    applies regardless of which auth-checking endpoint the attacker
    chose.

    Audit fix H-NEW-2 (2026-04-27): the increment is now an atomic SQL
    UPDATE (`failed_login_attempts = failed_login_attempts + 1`)
    instead of a Python-side read-modify-write. The old
    `user.foo = (user.foo or 0) + 1` pattern lost increments under
    concurrent failed logins — two requests both read N, both wrote
    N+1 — effectively raising the lockout threshold to ~10-15 attempts
    instead of 5. The CASE expression also stamps locked_until in the
    same statement so the lock fires on the *committing* request even
    when racing.
    """
    if user is None:
        return
    from sqlalchemy import update as _sql_update, case as _sql_case
    db = _db()
    pre_attempts = user.failed_login_attempts or 0
    new_lock_at = datetime.utcnow() + LOCKOUT_DURATION
    stmt = (
        _sql_update(User)
        .where(User.id == user.id)
        .values(
            failed_login_attempts=User.failed_login_attempts + 1,
            locked_until=_sql_case(
                (User.failed_login_attempts + 1 >= LOCKOUT_THRESHOLD,
                 new_lock_at),
                else_=User.locked_until,
            ),
        )
        .execution_options(synchronize_session=False)
    )
    try:
        db.session.execute(stmt)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return
    db.session.refresh(user)
    audit_meta: dict = {
        "reason": "bad_password",
        "endpoint": endpoint,
        "attempts": user.failed_login_attempts,
    }
    just_locked = (
        user.failed_login_attempts >= LOCKOUT_THRESHOLD
        and pre_attempts < LOCKOUT_THRESHOLD
    )
    if just_locked:
        audit_meta["locked_until"] = user.locked_until.isoformat() + 'Z'
        _audit('account.locked', user.id, audit_meta)
    elif user.failed_login_attempts < LOCKOUT_THRESHOLD:
        _audit('login.fail', user.id, audit_meta)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


# ── PR #39: KMS-wrapped TOTP secret ─────────────────────────────────────

def _wrap_totp_secret(plain: str) -> str:
    """Encrypt a plaintext TOTP secret for storage in
    User.totp_secret_enc. With NoopKms this is base64(plain) — still
    distinguishable from a NULL totp_secret_enc, so the read path can
    prefer it deterministically."""
    import base64
    if not plain:
        return ''
    ct = get_kms().encrypt(plain.encode('utf-8'))
    return base64.b64encode(ct).decode('ascii')


def _unwrap_totp_secret(user) -> str | None:
    """Return the plaintext TOTP secret for `user`, preferring the
    KMS-wrapped column when populated and falling back to the legacy
    plaintext `totp_secret` for rows minted before PR #39. Returns None
    when the user has no secret at all."""
    import base64
    enc = getattr(user, 'totp_secret_enc', None)
    if enc:
        try:
            ct = base64.b64decode(enc)
            return get_kms().decrypt(ct).decode('utf-8')
        except Exception:
            logger.exception(
                "Failed to unwrap totp_secret_enc for user_id=%s — "
                "falling back to plaintext column", user.id)
    return user.totp_secret or None


# ── PR #15: audit log ──────────────────────────────────────────────────────

def _redact_ip(s: str) -> str:
    """GDPR — drop the last octet (IPv4) or last 80 bits (IPv6).
    Empty / unparseable → empty (don't store junk)."""
    if not s:
        return ''
    first = s.split(',')[0].strip()
    try:
        import ipaddress
        ip = ipaddress.ip_address(first)
    except ValueError:
        return ''
    if isinstance(ip, ipaddress.IPv4Address):
        parts = str(ip).split('.')
        parts[-1] = '0'
        return '.'.join(parts)
    net = ipaddress.ip_network(f"{ip}/48", strict=False)
    return str(net.network_address)


def _compute_audit_row_hash(prev_hash: str, user_id: int, event_type: str,
                             ip: str, ua: str, meta_json: str | None,
                             created_at: datetime) -> str:
    """Audit fix M-NEW-7 (2026-04-27): canonical content hash that
    chains a row to its predecessor. SHA-256 over a `|`-joined record
    of the immutable fields. Tampering with any field on a stored row
    breaks the row's own hash; deleting a middle row breaks the next
    row's prev_hash linkage. Verifier walks user's events in
    (created_at, id) order and recomputes."""
    import hashlib
    content = "|".join([
        prev_hash or '',
        str(user_id),
        event_type,
        ip or '',
        ua or '',
        meta_json or '',
        created_at.isoformat(),
    ])
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


_AUDIT_TO_USER_ACTION = {
    'login.success':    'login_password',
    'logout':           'logout',
    'password.changed': 'password_change',
    'profile.updated':  'profile_update',
    '2fa.enabled':      'totp_setup',
    '2fa.disabled':     'totp_disable',
    'apikey.created':   'api_key_create',
    'apikey.revoked':   'api_key_revoke',
    'location.created': 'location_create',
    'location.updated': 'location_update',
    'location.deleted': 'location_delete',
    'snapshot.taken':   'location_snapshot',
}


def _audit(event_type: str, user_id: int, meta: dict | None = None) -> None:
    """Record a security-sensitive action against `user_id`. Caller is
    responsible for committing the txn — we add the row to the session so
    it lands atomically with whatever business write triggered it.

    Hash chain (M-NEW-7): each row carries `prev_hash` (the row_hash of
    the previous AuditEvent for this user, or '' if first) and
    `row_hash` (sha256 of prev_hash + this row's canonical content).
    Verification via verify_audit_chain_for_user(). Best-effort like
    the rest of audit logging — a chain-stamp failure must not break
    the business action."""
    try:
        raw_ip = (request.headers.get('X-Forwarded-For')
                  or request.remote_addr or '')
        ip = _redact_ip(raw_ip)[:64]
        ua = (request.headers.get('User-Agent') or '')[:256]
        meta_json_str = json.dumps(meta) if meta else None
        created_at = datetime.utcnow()

        sess = _db().session
        last_pending = next(
            (obj for obj in reversed(list(sess.new))
             if isinstance(obj, AuditEvent) and obj.user_id == user_id),
            None,
        )
        if last_pending is not None:
            prev_hash = last_pending.row_hash or ''
        else:
            prev = (AuditEvent.query
                    .filter_by(user_id=user_id)
                    .order_by(AuditEvent.created_at.desc(),
                              AuditEvent.id.desc())
                    .first())
            prev_hash = (prev.row_hash if prev and prev.row_hash else '')
        row_hash = _compute_audit_row_hash(
            prev_hash, user_id, event_type, ip, ua, meta_json_str, created_at,
        )

        ev = AuditEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=ip,
            user_agent=ua,
            meta_json=meta_json_str,
            created_at=created_at,
            prev_hash=prev_hash,
            row_hash=row_hash,
        )
        sess.add(ev)
    except Exception:
        logger.exception("Failed to record audit event %s for user_id=%s",
                         event_type, user_id)
    action = _AUDIT_TO_USER_ACTION.get(event_type)
    if action is not None:
        try:
            from observability import user_action_total, request_user_class
            user_action_total.labels(
                action=action,
                user_class=request_user_class(),
            ).inc()
        except Exception:
            pass


def verify_audit_chain_for_user(user_id: int) -> tuple[bool, list[int]]:
    """Walk user's AuditEvent rows in (created_at, id) order. Returns
    (is_valid, list_of_broken_event_ids). A row is "broken" if either:
    - its `prev_hash` doesn't match the prior row's `row_hash`, OR
    - its `row_hash` doesn't match what we'd recompute.

    Use this in admin tooling / a daily cron to spot tampering. The
    chain itself is per-user, so a row deleted via /account/delete
    cascade does NOT show up as broken — that's a legit teardown.
    M-NEW-7 (audit 2026-04-27).
    """
    rows = (AuditEvent.query
            .filter_by(user_id=user_id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
            .all())
    broken: list[int] = []
    expected_prev = ''
    for row in rows:
        if (row.prev_hash or '') != expected_prev:
            broken.append(row.id)
            expected_prev = row.row_hash or ''
            continue
        recomputed = _compute_audit_row_hash(
            row.prev_hash or '', row.user_id, row.event_type,
            row.ip_address or '', row.user_agent or '', row.meta_json,
            row.created_at,
        )
        if (row.row_hash or '') != recomputed:
            broken.append(row.id)
        expected_prev = row.row_hash or ''
    return (not broken, broken)


def register_auth_routes(app, *, bcrypt, db, limiter, validate_csrf,
                         generate_api_key, csrf_failures_total,
                         login_failures_total):
    """Wire dependencies and register the blueprint on the app.

    Done as a function call rather than a top-level import so app.py
    controls the lifecycle (db must be initialized first).
    """
    _deps.update({
        "bcrypt": bcrypt,
        "db": db,
        "limiter": limiter,
        "validate_csrf": validate_csrf,
        "generate_api_key": generate_api_key,
        "csrf_failures_total": csrf_failures_total,
        "login_failures_total": login_failures_total,
    })

    auth_bp.add_url_rule(
        "/register", endpoint="register",
        view_func=limiter.limit(
            "5 per hour", key_func=_register_rate_key)(register_user),
        methods=["POST"])
    auth_bp.add_url_rule(
        "/login", endpoint="login",
        view_func=limiter.limit(
            "10 per minute", key_func=_login_rate_key)(login_user),
        methods=["POST"])
    auth_bp.add_url_rule("/logout", endpoint="logout",
                         view_func=logout, methods=["POST"])
    auth_bp.add_url_rule("/forgot-password", endpoint="forgot_password_page",
                         view_func=forgot_password_page, methods=["GET"])
    auth_bp.add_url_rule(
        "/forgot-password", endpoint="forgot_password",
        view_func=limiter.limit(
            "5 per hour", key_func=_forgot_password_rate_key)(forgot_password),
        methods=["POST"])
    auth_bp.add_url_rule("/reset-password", endpoint="reset_password_page",
                         view_func=reset_password_page, methods=["GET"])
    auth_bp.add_url_rule("/verify-email", endpoint="verify_email",
                         view_func=limiter.limit("20 per hour")(verify_email),
                         methods=["GET"])
    auth_bp.add_url_rule("/account/resend_verification",
                         endpoint="resend_verification",
                         view_func=limiter.limit(
                             "3 per hour")(resend_verification),
                         methods=["POST"])
    auth_bp.add_url_rule(
        "/reset-password", endpoint="reset_password",
        view_func=limiter.limit("10 per hour")(reset_password),
        methods=["POST"])
    auth_bp.add_url_rule("/session_check", endpoint="session_check",
                         view_func=session_check, methods=["GET"])
    auth_bp.add_url_rule("/account", endpoint="account_page",
                         view_func=account_page, methods=["GET"])
    auth_bp.add_url_rule("/account/regenerate_api_key",
                         endpoint="regenerate_api_key",
                         view_func=limiter.limit("3 per hour")(regenerate_api_key),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/profile", endpoint="update_profile",
                         view_func=limiter.limit("20 per hour")(update_profile),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/password", endpoint="change_password",
                         view_func=limiter.limit("5 per hour")(change_password),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/delete", endpoint="delete_account",
                         view_func=limiter.limit("3 per hour")(delete_account),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/keys", endpoint="create_api_key",
                         view_func=limiter.limit("10 per hour")(create_api_key),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/keys/<int:key_id>/revoke",
                         endpoint="revoke_api_key",
                         view_func=limiter.limit("20 per hour")(revoke_api_key),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/2fa/setup", endpoint="totp_setup",
                         view_func=limiter.limit("10 per hour")(totp_setup),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/2fa/verify", endpoint="totp_verify",
                         view_func=limiter.limit("10 per hour")(totp_verify),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/2fa/disable", endpoint="totp_disable",
                         view_func=limiter.limit("5 per hour")(totp_disable),
                         methods=["POST"])
    auth_bp.add_url_rule("/login/totp", endpoint="login_totp",
                         view_func=limiter.limit("10 per minute")(login_totp),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/2fa/regenerate", endpoint="totp_regenerate",
                         view_func=limiter.limit("5 per hour")(totp_regenerate),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/snapshot", endpoint="take_snapshot",
                         view_func=limiter.limit("6 per hour")(take_snapshot),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/changes", endpoint="changes_page",
                         view_func=changes_page, methods=["GET"])
    auth_bp.add_url_rule("/account/locations", endpoint="create_location",
                         view_func=limiter.limit("20 per hour")(create_location),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/locations/<int:loc_id>",
                         endpoint="get_location",
                         view_func=get_location, methods=["GET"])
    auth_bp.add_url_rule("/account/locations/<int:loc_id>",
                         endpoint="update_location",
                         view_func=limiter.limit("30 per hour")(update_location),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/locations/<int:loc_id>/delete",
                         endpoint="delete_location",
                         view_func=limiter.limit("10 per hour")(delete_location),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/locations/<int:loc_id>/snapshot",
                         endpoint="take_location_snapshot",
                         view_func=limiter.limit("10 per hour")(take_location_snapshot),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/locations/<int:loc_id>/changes",
                         endpoint="location_changes_page",
                         view_func=location_changes_page, methods=["GET"])

    app.register_blueprint(auth_bp)


# ── Email-normalization + disposable-domain blocklist (2026-04-29) ─────────

_GMAIL_DOMAINS = {'gmail.com', 'googlemail.com'}

_DISPOSABLE_DOMAINS = frozenset([
    '10minutemail.com', '10minutemail.net', 'mailinator.com',
    'mailinator.net', 'guerrillamail.com', 'guerrillamail.net',
    'guerrillamail.org', 'guerrillamail.biz', 'guerrillamail.de',
    'sharklasers.com', 'grr.la', 'spam4.me', 'pokemail.net',
    'yopmail.com', 'yopmail.net', 'yopmail.fr', 'tempmail.com',
    'tempmail.net', 'tempmail.org', 'temp-mail.org', 'temp-mail.io',
    'throwawaymail.com', 'mohmal.com', 'getnada.com', 'maildrop.cc',
    'fakeinbox.com', 'trashmail.com', 'dispostable.com', 'mailnesia.com',
    'spamgourmet.com', 'mintemail.com', 'mytemp.email', 'tmpmail.org',
    'tmpmail.net', 'mailcatch.com', 'discard.email', 'discardmail.com',
    'jetable.org', 'spamcorptastic.com', 'spamfree24.org', 'mvrht.com',
    'inboxalias.com', 'mailtemp.info', 'rcpt.at', 'incognitomail.com',
    'tempinbox.com', 'tempr.email', 'mailnull.com', 'spambox.us',
])


def _normalize_email(raw: str) -> str:
    """Lowercase, strip, and collapse Gmail dot-and-plus aliasing so
    duplicate-checks AND storage match a real-world inbox 1:1.

    Examples:
      `User+test@gmail.com`     -> `user@gmail.com`
      `u.s.e.r@gmail.com`       -> `user@gmail.com`
      `me+anything@googlemail.com` -> `me@gmail.com`  (canonical alias)
      `me@example.com`          -> `me@example.com`  (non-Gmail untouched)
    """
    if not raw:
        return ''
    addr = raw.strip().lower()
    if '@' not in addr:
        return addr
    local, _, domain = addr.partition('@')
    local = local.split('+', 1)[0]
    if domain in _GMAIL_DOMAINS:
        local = local.replace('.', '')
        domain = 'gmail.com'  # canonicalise googlemail.com -> gmail.com
    return f"{local}@{domain}"


def _is_disposable_email_domain(email: str) -> bool:
    """True iff the domain part is on the throwaway-providers blocklist.
    Email is expected to have already been normalized (lowercase)."""
    if '@' not in email:
        return False
    return email.rsplit('@', 1)[1] in _DISPOSABLE_DOMAINS


# ── View functions ──────────────────────────────────────────────────────────

def register_user():
    funnel_register_started_total.inc()
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='register').inc()
        return jsonify({'error': 'Invalid request'}), 403

    if (request.form.get('website_url') or '').strip():
        logger.info("[register] honeypot triggered (suspected bot)")
        return jsonify({"success": True,
                        "message": "User registered successfully."}), 200

    email_raw = (request.form.get('email') or '').strip()
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if not email_raw or not re.fullmatch(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email_raw
    ):
        return "Invalid email address.", 400

    email = _normalize_email(email_raw)

    if _is_disposable_email_domain(email):
        logger.info("[register] blocked disposable-domain signup: domain=%s",
                    email.rpartition('@')[2])
        return "Please use a non-disposable email address.", 400

    if not password or not re.fullmatch(
        r"(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[^\w\s]).{8,64}$", password
    ):
        return "Password does not meet criteria.", 400

    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match.'}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user is not None:
        _bcrypt().check_password_hash(_DUMMY_BCRYPT_HASH, password)
        return jsonify({"success": True, "message": "User registered successfully."}), 200

    hashed_password = _bcrypt().generate_password_hash(password).decode('utf-8')

    try:
        raw_key = _generate_api_key()
        user = User(
            email=email,
            password_hash=hashed_password,
            api_key=None,
            api_key_hash=hash_api_key(raw_key),
            api_key_prefix=format_api_key_prefix(raw_key),
            api_tier='free',
        )
        _db().session.add(user)
        _db().session.commit()
        _send_verification_email(user)
        funnel_register_completed_total.inc()
        try:
            from observability import user_action_total, request_user_class
            user_action_total.labels(
                action='register', user_class=request_user_class(),
            ).inc()
        except Exception:
            pass
        return jsonify({"success": True, "message": "User registered successfully."}), 200
    except Exception:
        _db().session.rollback()
        logger.exception("Error registering user")
        return jsonify({"success": False, "message": "Registration failed due to a server error."}), 500


def login_user():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='login').inc()
        return jsonify({'error': 'Invalid request'}), 403

    email_raw = request.form.get('email') or ''
    password = request.form.get('password')

    email = _normalize_email(email_raw)
    user = User.query.filter_by(email=email).first()
    if user is None and email != email_raw.strip().lower():
        user = User.query.filter_by(email=email_raw.strip().lower()).first()
    if user is None and email_raw != email_raw.lower():
        user = User.query.filter_by(email=email_raw).first()

    if user is None:
        _bcrypt().check_password_hash(_DUMMY_BCRYPT_HASH, password or '')

    is_locked = False
    if user is not None and user.locked_until is not None:
        if user.locked_until > datetime.utcnow():
            is_locked = True
        else:
            user.locked_until = None

    password_ok = bool(
        user and _bcrypt().check_password_hash(user.password_hash, password)
    )

    if password_ok and is_locked:
        _login_failures_total().inc()
        _audit('login.locked', user.id, {
            "locked_until": user.locked_until.isoformat() + 'Z',
        })
        try:
            _db().session.commit()
        except Exception:
            _db().session.rollback()
        return jsonify({
            "success": False,
            "locked": True,
            "message": "Account is temporarily locked due to too many failed attempts.",
            "locked_until": user.locked_until.isoformat() + 'Z',
        }), 403

    if password_ok and not is_locked:
        # Successful auth — reset lockout state.
        user.failed_login_attempts = 0
        user.locked_until = None

        import secrets
        new_csrf = secrets.token_hex(32)

        if user.totp_enabled:
            session.clear()
            session['_csrf_token'] = new_csrf
            session['pending_2fa_user_id'] = user.id
            session['pending_2fa_started_at'] = datetime.utcnow().isoformat()
            try:
                _db().session.commit()  # persist the failed-attempts reset
            except Exception:
                _db().session.rollback()
            return jsonify({
                "success": False,
                "totp_required": True,
                "message": "2FA code required.",
                "csrf_token": new_csrf,
            }), 200

        session.clear()
        session['_csrf_token'] = new_csrf
        session['user_id'] = user.id
        _audit('login.success', user.id)
        try:
            _db().session.commit()
        except Exception:
            _db().session.rollback()
        return jsonify({
            "success": True,
            "message": "Logged in successfully.",
            "csrf_token": new_csrf,
        }), 200
    else:
        _login_failures_total().inc()
        _record_failed_password_attempt(user, endpoint='login')
        return jsonify({"success": False, "message": "Invalid email or password."}), 401


def logout():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='logout').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user_id = session.get('user_id')
    session.clear()
    if user_id:
        _audit('logout', user_id)
        try:
            _db().session.commit()
        except Exception:
            _db().session.rollback()
    return jsonify({"success": True, "message": "You have been logged out."}), 200


def session_check():
    is_logged_in = 'user_id' in session
    return jsonify({"logged_in": is_logged_in})


def account_page():
    if 'user_id' not in session:
        return jsonify({"error": "Authentication required"}), 401
    user = _db().session.get(User, session['user_id'])
    if not user:
        session.pop('user_id', None)
        return jsonify({"error": "Authentication required"}), 401
    if not user.api_key and not user.api_key_hash:
        raw_key = _generate_api_key()
        user.api_key_hash = hash_api_key(raw_key)
        user.api_key_prefix = format_api_key_prefix(raw_key)
        user.api_tier = user.api_tier or 'free'
        _db().session.commit()
    api_keys = (ApiKey.query
                .filter_by(user_id=user.id)
                .order_by(ApiKey.revoked_at.is_(None).desc(), ApiKey.created_at.desc())
                .all())
    audit_events = (AuditEvent.query
                    .filter_by(user_id=user.id)
                    .order_by(AuditEvent.created_at.desc())
                    .limit(20)
                    .all())
    locations = (UserLocation.query
                 .filter_by(user_id=user.id)
                 .order_by(UserLocation.created_at.desc())
                 .all())
    quick_stats = {
        "saved_locations": len(locations),
        "active_keys": sum(1 for k in api_keys if k.revoked_at is None),
        "two_fa_on": bool(getattr(user, 'totp_enabled', False)),
        "alerts_on": bool(getattr(user, 'email_alerts_enabled', True)),
    }
    return render_template('account.html', user=user,
                           api_keys=api_keys, audit_events=audit_events,
                           locations=locations, quick_stats=quick_stats)


def regenerate_api_key():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='regenerate_api_key').inc()
        return jsonify({'error': 'Invalid request'}), 403
    if 'user_id' not in session:
        return jsonify({"error": "Authentication required"}), 401
    user = _db().session.get(User, session['user_id'])
    if not user:
        session.pop('user_id', None)
        return jsonify({"error": "Authentication required"}), 401
    raw_key = _generate_api_key()
    user.api_key = None
    user.api_key_hash = hash_api_key(raw_key)
    user.api_key_prefix = format_api_key_prefix(raw_key)
    _db().session.commit()
    return jsonify({"success": True, "api_key": raw_key}), 200


# ── PR #12: profile / change password / delete account ─────────────────────

_PASSWORD_REGEX = re.compile(r"(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[^\w\s]).{8,64}$")


def _current_user_or_401():
    """Return (user, None) if authed, else (None, 401_response)."""
    if 'user_id' not in session:
        return None, (jsonify({"error": "Authentication required"}), 401)
    user = _db().session.get(User, session['user_id'])
    if not user:
        session.pop('user_id', None)
        return None, (jsonify({"error": "Authentication required"}), 401)
    return user, None


def update_profile():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='update_profile').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err

    # Accept both form-encoded and JSON for friendlier curl/UX.
    payload = request.get_json(silent=True) or request.form

    if 'company' in payload:
        company = (payload.get('company') or '').strip() or None
        if company and len(company) > 120:
            return jsonify({'error': 'company too long'}), 400
        user.company = company

    _audit('profile.updated', user.id)
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("update_profile commit failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not save profile'}), 500
    return jsonify({'success': True}), 200


def change_password():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='change_password').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err

    if _is_locked(user):
        return jsonify({
            "success": False,
            "locked": True,
            "message": "Account is temporarily locked due to too many failed attempts.",
            "locked_until": user.locked_until.isoformat() + 'Z',
        }), 403

    payload = request.get_json(silent=True) or request.form
    current = payload.get('current_password') or ''
    new = payload.get('new_password') or ''
    confirm = payload.get('confirm_password') or ''

    if not _bcrypt().check_password_hash(user.password_hash, current):
        _login_failures_total().inc()
        _record_failed_password_attempt(user, endpoint='change_password')
        return jsonify({'error': 'Current password is incorrect'}), 401

    if not _PASSWORD_REGEX.fullmatch(new):
        return jsonify({'error': 'New password does not meet criteria'}), 400
    if new != confirm:
        return jsonify({'error': 'Passwords do not match'}), 400
    if new == current:
        return jsonify({'error': 'New password must differ from current'}), 400

    user.password_hash = _bcrypt().generate_password_hash(new).decode('utf-8')
    user.last_password_change = datetime.utcnow()
    _audit('password.changed', user.id)
    import secrets
    new_csrf = secrets.token_hex(32)
    session.clear()
    session['_csrf_token'] = new_csrf
    session['user_id'] = user.id
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("change_password commit failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not save password'}), 500
    try:
        from emails import send_password_changed
        send_password_changed(user)
    except Exception:
        logger.exception("send_password_changed failed for user_id=%s", user.id)
    return jsonify({'success': True, 'csrf_token': new_csrf}), 200


# ── Password reset (forgot-password), 2026-06-08 ───────────────────────────
_PW_RESET_SALT = "password-reset"
_PW_RESET_MAX_AGE = 3600  # 1 hour
_PW_RESET_GENERIC_MESSAGE = (
    "If an account exists for that email, we've sent a password reset link."
)


def _pw_reset_serializer():
    from itsdangerous import URLSafeTimedSerializer
    from config import settings
    return URLSafeTimedSerializer(settings.secret_key, salt=_PW_RESET_SALT)


def _password_fingerprint(password_hash: str | None) -> str:
    """First 16 hex chars of sha256(current password hash). Embedded in the
    reset token so a hash change (i.e. a completed reset) invalidates the
    token — the single-use mechanism."""
    import hashlib
    return hashlib.sha256((password_hash or '').encode('utf-8')).hexdigest()[:16]


def _make_password_reset_token(user) -> str:
    return _pw_reset_serializer().dumps({
        "uid": user.id,
        "pwf": _password_fingerprint(user.password_hash),
    })


def _verify_password_reset_token(token: str):
    """Return the User for a valid, unexpired, hash-bound token, else None.
    Treats expired / tampered / malformed tokens identically (None)."""
    from itsdangerous import SignatureExpired, BadSignature, BadData
    if not token:
        return None
    try:
        data = _pw_reset_serializer().loads(token, max_age=_PW_RESET_MAX_AGE)
    except (SignatureExpired, BadSignature, BadData):
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    pwf = data.get("pwf")
    if uid is None or pwf is None:
        return None
    user = _db().session.get(User, uid)
    if user is None or not user.password_hash:
        return None
    if pwf != _password_fingerprint(user.password_hash):
        return None
    return user


def _password_reset_url(token: str) -> str:
    from config import settings
    origin = (settings.email_link_origin or '').rstrip('/')
    return f"{origin}/reset-password?token={token}"


# ── Email verification, 2026-06-11 ─────────────────────────────────────────
_EMAIL_VERIFY_SALT = "email-verify"
_EMAIL_VERIFY_MAX_AGE = 172800  # 48 hours


def _email_verify_serializer():
    from itsdangerous import URLSafeTimedSerializer
    from config import settings
    return URLSafeTimedSerializer(settings.secret_key, salt=_EMAIL_VERIFY_SALT)


def _make_email_verify_token(user) -> str:
    return _email_verify_serializer().dumps({"uid": user.id, "em": user.email})


def _verify_email_token(token: str):
    """Return the User for a valid, unexpired, email-bound token, else None."""
    from itsdangerous import SignatureExpired, BadSignature, BadData
    if not token:
        return None
    try:
        data = _email_verify_serializer().loads(
            token, max_age=_EMAIL_VERIFY_MAX_AGE)
    except (SignatureExpired, BadSignature, BadData):
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    em = data.get("em")
    if uid is None or em is None:
        return None
    user = _db().session.get(User, uid)
    if user is None or user.email != em:
        return None
    return user


def _email_verification_url(token: str) -> str:
    from config import settings
    origin = (settings.email_link_origin or '').rstrip('/')
    return f"{origin}/verify-email?token={token}"


def _send_verification_email(user) -> bool:
    """Best-effort — an email-backend outage must never block /register."""
    try:
        from emails import send_welcome
        return send_welcome(
            user, _email_verification_url(_make_email_verify_token(user)))
    except Exception:
        logger.exception("verification email failed for user_id=%s", user.id)
        return False


def verify_email():
    user = _verify_email_token(request.args.get('token', ''))
    if user is None:
        return render_template('verify_email.html', outcome='invalid'), 400
    if user.email_verified_at is None:
        user.email_verified_at = datetime.utcnow()
        _audit('email_verified', user.id)
        try:
            _db().session.commit()
        except Exception:
            _db().session.rollback()
            logger.exception("verify_email commit failed for user_id=%s",
                             user.id)
            return render_template('verify_email.html', outcome='error'), 500
    return render_template('verify_email.html', outcome='ok')


def resend_verification():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='resend_verification').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err
    if user.email_verified_at is not None:
        return jsonify({'success': True,
                        'message': 'Email is already verified.'}), 200
    _send_verification_email(user)
    return jsonify({'success': True,
                    'message': 'Verification email sent.'}), 200


def forgot_password_page():
    return render_template('forgot_password.html')


def forgot_password():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='forgot_password').inc()
        return jsonify({'error': 'Invalid request'}), 403

    email = _normalize_email((request.form.get('email') or '').strip())
    user = User.query.filter_by(email=email).first() if email else None

    if user is not None and user.password_hash:
        try:
            token = _make_password_reset_token(user)
            from emails import send_password_reset
            send_password_reset(user, _password_reset_url(token))
        except Exception:
            logger.exception(
                "send_password_reset failed for user_id=%s", user.id)
    else:
        _bcrypt().check_password_hash(_DUMMY_BCRYPT_HASH, "x")

    return render_template('forgot_password.html',
                           message=_PW_RESET_GENERIC_MESSAGE), 200


def reset_password_page():
    token = request.args.get('token') or ''
    user = _verify_password_reset_token(token)
    if user is None:
        return render_template(
            'reset_password.html', valid=False,
            error="This reset link is invalid or has expired."), 400
    return render_template('reset_password.html', valid=True, token=token)


def reset_password():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='reset_password').inc()
        return jsonify({'error': 'Invalid request'}), 403

    token = request.form.get('token') or ''
    user = _verify_password_reset_token(token)
    if user is None:
        return render_template(
            'reset_password.html', valid=False,
            error="This reset link is invalid or has expired."), 400

    password = request.form.get('password') or ''
    confirm = request.form.get('confirm_password')
    if not _PASSWORD_REGEX.fullmatch(password):
        return render_template(
            'reset_password.html', valid=True, token=token,
            error="Password does not meet criteria."), 400
    if confirm is not None and password != confirm:
        return render_template(
            'reset_password.html', valid=True, token=token,
            error="Passwords do not match."), 400

    user.password_hash = _bcrypt().generate_password_hash(password).decode('utf-8')
    user.last_password_change = datetime.utcnow()
    user.failed_login_attempts = 0
    user.locked_until = None
    _audit('password.reset', user.id, {"via": "forgot_password"})
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("reset_password commit failed for user_id=%s", user.id)
        return render_template(
            'reset_password.html', valid=True, token=token,
            error="Could not update password. Please try again."), 500

    try:
        from emails import send_password_changed
        send_password_changed(user)
    except Exception:
        logger.exception(
            "send_password_changed failed after reset for user_id=%s", user.id)

    return render_template('reset_password.html', success=True), 200


def delete_account():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='delete_account').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err

    if _is_locked(user):
        return jsonify({
            "success": False,
            "locked": True,
            "message": "Account is temporarily locked due to too many failed attempts.",
            "locked_until": user.locked_until.isoformat() + 'Z',
        }), 403

    payload = request.get_json(silent=True) or request.form
    confirm_password = payload.get('current_password') or ''
    confirm_phrase = (payload.get('confirm_phrase') or '').strip()

    if not _bcrypt().check_password_hash(user.password_hash, confirm_password):
        _login_failures_total().inc()
        _record_failed_password_attempt(user, endpoint='delete_account')
        return jsonify({'error': 'Current password is incorrect'}), 401
    if confirm_phrase != 'DELETE':
        return jsonify({'error': "Type DELETE to confirm"}), 400

    user_id = user.id
    try:
        ApiKey.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        from models import EmailEvent
        from sqlalchemy import func as _func
        EmailEvent.query.filter(
            _func.lower(EmailEvent.email) == user.email.lower()
        ).delete(synchronize_session=False)
        _db().session.delete(user)
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("delete_account commit failed for user_id=%s", user_id)
        return jsonify({'error': 'Could not delete account'}), 500
    session.clear()
    return jsonify({'success': True}), 200


# ── PR #14: multi-key API ──────────────────────────────────────────────────

_MAX_KEY_NAME_LEN = 80
_MAX_ACTIVE_KEYS_PER_USER = 10


def create_api_key():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='create_api_key').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err

    payload = request.get_json(silent=True) or request.form
    name = (payload.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    if len(name) > _MAX_KEY_NAME_LEN:
        return jsonify({'error': 'name too long'}), 400

    active_count = ApiKey.query.filter_by(
        user_id=user.id, revoked_at=None
    ).count()
    if active_count >= _MAX_ACTIVE_KEYS_PER_USER:
        return jsonify({
            'error': f'Active key limit reached ({_MAX_ACTIVE_KEYS_PER_USER}). Revoke one first.'
        }), 400

    if ApiKey.query.filter_by(user_id=user.id).count() <= 1:
        funnel_first_api_key_created_total.inc()
    new_key_value = _generate_api_key()
    ak = ApiKey(
        user_id=user.id,
        name=name,
        key=None,
        key_hash=hash_api_key(new_key_value),
        key_prefix=format_api_key_prefix(new_key_value),
    )
    _db().session.add(ak)
    try:
        _db().session.flush()  # need ak.id for the audit meta below
    except Exception:
        _db().session.rollback()
        logger.exception("create_api_key flush failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not create key'}), 500
    _audit('apikey.created', user.id, {'name': name, 'key_id': ak.id})
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("create_api_key commit failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not create key'}), 500

    return jsonify({
        'success': True,
        'id': ak.id,
        'name': ak.name,
        'key': new_key_value,  # one-shot reveal — never returned again
        'key_prefix': ak.key_prefix,
        'created_at': ak.created_at.isoformat() + 'Z',
    }), 200


def revoke_api_key(key_id: int):
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='revoke_api_key').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err

    ak = _db().session.get(ApiKey, key_id)
    if ak is None or ak.user_id != user.id:
        return jsonify({'error': 'Not found'}), 404
    if ak.revoked_at is not None:
        return jsonify({'error': 'Already revoked'}), 400

    from datetime import datetime
    ak.revoked_at = datetime.utcnow()
    if ak.name == 'default':
        if user.api_key is not None and user.api_key == ak.key:
            user.api_key = None
        if user.api_key_hash is not None and user.api_key_hash == ak.key_hash:
            user.api_key_hash = None
            user.api_key_prefix = None
    _audit('apikey.revoked', user.id, {'name': ak.name, 'key_id': ak.id})
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("revoke_api_key commit failed for key_id=%s", key_id)
        return jsonify({'error': 'Could not revoke key'}), 500
    return jsonify({'success': True}), 200


# ── PR #16: 2FA TOTP ───────────────────────────────────────────────────────

_ISSUER = "signal-scout"
_TOTP_VALID_WINDOW = 1
_RECOVERY_CODE_COUNT = 10
_PENDING_2FA_TTL_SECS = 300  # 5 minutes is plenty for a code prompt
_TOTP_REPLAY_WINDOW_SECS = (2 * _TOTP_VALID_WINDOW + 1) * 30


def _pyotp():
    import pyotp
    return pyotp


def _verify_totp_with_replay_protection(user, code: str) -> bool:
    """Verify a TOTP code AND ensure it hasn't been used recently.

    Returns True only if both checks pass. On success, stamps
    user.last_totp_code + last_totp_code_at so a re-presentation of
    the same code within _TOTP_REPLAY_WINDOW_SECS is rejected. Does
    NOT commit — the caller controls the surrounding transaction
    (login_totp commits after promoting to a full session, totp_disable
    commits when wiping the secret).

    Audit fix M-NEW-3 (2026-04-27).
    """
    if not code:
        return False
    secret = _unwrap_totp_secret(user)
    if not _pyotp().TOTP(secret).verify(code, valid_window=_TOTP_VALID_WINDOW):
        return False
    now = datetime.utcnow()
    if (user.last_totp_code == code
            and user.last_totp_code_at is not None
            and (now - user.last_totp_code_at).total_seconds()
                < _TOTP_REPLAY_WINDOW_SECS):
        return False
    user.last_totp_code = code
    user.last_totp_code_at = now
    return True


def _generate_recovery_codes() -> list[str]:
    """10 human-friendly single-use codes. Lowercase base32, hyphen-separated
    for easier manual entry when the user loses their authenticator app."""
    import secrets as _s
    alphabet = 'abcdefghjkmnpqrstvwxyz23456789'  # no 0/O/1/I/l ambiguity
    codes = []
    for _ in range(_RECOVERY_CODE_COUNT):
        part_a = ''.join(_s.choice(alphabet) for _ in range(5))
        part_b = ''.join(_s.choice(alphabet) for _ in range(5))
        codes.append(f"{part_a}-{part_b}")
    return codes


def totp_setup():
    """Step 1: generate a secret + provisioning URI. No DB commit yet —
    the secret only becomes 'real' after totp_verify confirms the user
    has successfully scanned the QR and can produce a valid code."""
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='totp_setup').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err
    if user.totp_enabled:
        return jsonify({'error': '2FA already enabled. Disable first to reconfigure.'}), 400

    pyotp = _pyotp()
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=_ISSUER)

    import segno
    qr = segno.make(uri, error='M')
    qr_svg = qr.svg_inline(scale=5, dark='#111827', light='#ffffff', border=2)

    session['pending_totp_secret'] = secret
    return jsonify({
        'success': True,
        'secret': secret,
        'otpauth_uri': uri,
        'qr_svg': qr_svg,
    }), 200


def totp_verify():
    """Step 2: user submits a code; we verify against pending_totp_secret,
    move the secret onto User.totp_secret, flip totp_enabled=True, mint
    fresh recovery codes (returned ONCE here — never again)."""
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='totp_verify').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err

    payload = request.get_json(silent=True) or request.form
    code = (payload.get('code') or '').strip().replace(' ', '')
    pending = session.get('pending_totp_secret')
    if not pending:
        return jsonify({'error': 'No setup in progress. Call /account/2fa/setup first.'}), 400
    if not code:
        return jsonify({'error': 'Code is required'}), 400
    if not _pyotp().TOTP(pending).verify(code, valid_window=_TOTP_VALID_WINDOW):
        return jsonify({'error': 'Invalid code'}), 401

    # Accept: move secret to user, enable, mint recovery codes.
    import json as _json
    recovery = _generate_recovery_codes()
    recovery_hashes = [
        _bcrypt().generate_password_hash(c).decode('utf-8') for c in recovery
    ]
    user.totp_secret_enc = _wrap_totp_secret(pending)
    user.totp_secret = None
    user.totp_enabled = True
    user.recovery_codes_json = _json.dumps(recovery_hashes)
    session.pop('pending_totp_secret', None)
    _audit('2fa.enabled', user.id)
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("totp_verify commit failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not save 2FA'}), 500
    return jsonify({
        'success': True,
        'recovery_codes': recovery,
    }), 200


def totp_disable():
    """Require password + valid TOTP code to turn 2FA off. Clears secret
    and recovery codes."""
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='totp_disable').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err
    if not user.totp_enabled:
        return jsonify({'error': '2FA is not enabled'}), 400

    if _is_locked(user):
        return jsonify({
            "error": "Account is temporarily locked due to too many failed attempts.",
            "locked": True,
            "locked_until": user.locked_until.isoformat() + 'Z',
        }), 403

    payload = request.get_json(silent=True) or request.form
    password = payload.get('current_password') or ''
    code = (payload.get('code') or '').strip().replace(' ', '')

    if not _bcrypt().check_password_hash(user.password_hash, password):
        _login_failures_total().inc()
        _record_failed_password_attempt(user, endpoint='totp_disable')
        return jsonify({'error': 'Current password is incorrect'}), 401
    if not _verify_totp_with_replay_protection(user, code):
        return jsonify({'error': 'Invalid 2FA code'}), 401

    user.totp_secret = None
    user.totp_secret_enc = None
    user.totp_enabled = False
    user.recovery_codes_json = None
    _audit('2fa.disabled', user.id)
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("totp_disable commit failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not save'}), 500
    try:
        from emails import send_2fa_disabled
        send_2fa_disabled(user)
    except Exception:
        logger.exception("send_2fa_disabled failed for user_id=%s", user.id)
    return jsonify({'success': True}), 200


def login_totp():
    """Second step of login for 2FA users. Consumes the pending_2fa_user_id
    marker set by login_user(). Accepts either a TOTP code OR a one-shot
    recovery code. On success: promote to a full session."""
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='login_totp').inc()
        return jsonify({'error': 'Invalid request'}), 403
    pending = session.get('pending_2fa_user_id')
    if not pending:
        return jsonify({'error': 'No 2FA step in progress'}), 400
    started_iso = session.get('pending_2fa_started_at')
    if started_iso:
        try:
            started = datetime.fromisoformat(started_iso)
        except (TypeError, ValueError):
            started = None
        if started and (datetime.utcnow() - started).total_seconds() > _PENDING_2FA_TTL_SECS:
            session.pop('pending_2fa_user_id', None)
            session.pop('pending_2fa_started_at', None)
            return jsonify({'error': '2FA session expired — sign in again'}), 401
    user = _db().session.get(User, pending)
    if not user or not user.totp_enabled:
        session.pop('pending_2fa_user_id', None)
        session.pop('pending_2fa_started_at', None)
        return jsonify({'error': 'No 2FA step in progress'}), 400

    payload = request.get_json(silent=True) or request.form
    code = (payload.get('code') or '').strip().replace(' ', '')

    used_recovery = False
    ok = False
    if code:
        if _verify_totp_with_replay_protection(user, code):
            ok = True
        else:
            # Try as a recovery code: compare against each stored hash.
            import json as _json
            from sqlalchemy import update as _sql_update
            old_json = user.recovery_codes_json or '[]'
            hashes = _json.loads(old_json)
            for idx, h in enumerate(list(hashes)):
                if _bcrypt().check_password_hash(h, code):
                    new_hashes = list(hashes)
                    new_hashes.pop(idx)
                    new_json = _json.dumps(new_hashes)
                    cas_stmt = (
                        _sql_update(User)
                        .where(User.id == user.id)
                        .where(User.recovery_codes_json == old_json)
                        .values(recovery_codes_json=new_json)
                        .execution_options(synchronize_session=False)
                    )
                    try:
                        result = _db().session.execute(cas_stmt)
                        _db().session.commit()
                    except Exception:
                        _db().session.rollback()
                        result = None
                    if result is not None and result.rowcount == 1:
                        ok = True
                        used_recovery = True
                    else:
                        _audit('login.2fa_recovery_race', user.id,
                               {'reason': 'cas_lost'})
                        try:
                            _db().session.commit()
                        except Exception:
                            _db().session.rollback()
                    break

    if not ok:
        _login_failures_total().inc()
        _record_failed_password_attempt(user, endpoint='login_totp')
        if _is_locked(user):
            session.pop('pending_2fa_user_id', None)
            session.pop('pending_2fa_started_at', None)
            return jsonify({
                "error": "locked",
                "locked": True,
                "message": "Too many wrong codes — account temporarily locked.",
                "locked_until": user.locked_until.isoformat() + 'Z',
            }), 403
        return jsonify({'error': 'Invalid code'}), 401

    import secrets
    new_csrf = secrets.token_hex(32)
    session.clear()
    session['_csrf_token'] = new_csrf
    session['user_id'] = user.id
    _audit('login.success',
           user.id,
           {'via': 'recovery_code'} if used_recovery else {'via': 'totp'})
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
    if used_recovery:
        try:
            from emails import send_recovery_code_used
            send_recovery_code_used(user)
        except Exception:
            logger.exception("send_recovery_code_used failed for user_id=%s", user.id)
    return jsonify({
        'success': True,
        'csrf_token': new_csrf,
    }), 200


def totp_regenerate():
    """PR #25: rotate TOTP secret without disabling 2FA. Mints a new
    candidate secret + QR (parked in session like setup), but caller must
    confirm with current password first to prove possession of the
    account. The current secret keeps working until totp_verify is called
    with a code from the new authenticator entry — at which point the
    swap is atomic (new secret + new recovery codes, old ones invalidated)."""
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='totp_regenerate').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err
    if not user.totp_enabled:
        return jsonify({'error': '2FA is not enabled — use /account/2fa/setup instead'}), 400

    if _is_locked(user):
        return jsonify({
            "error": "Account is temporarily locked due to too many failed attempts.",
            "locked": True,
            "locked_until": user.locked_until.isoformat() + 'Z',
        }), 403

    payload = request.get_json(silent=True) or request.form
    password = payload.get('current_password') or ''
    if not _bcrypt().check_password_hash(user.password_hash, password):
        _login_failures_total().inc()
        _record_failed_password_attempt(user, endpoint='totp_regenerate')
        return jsonify({'error': 'Current password is incorrect'}), 401

    pyotp = _pyotp()
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=_ISSUER)
    import segno
    qr_svg = segno.make(uri, error='M').svg_inline(
        scale=5, dark='#111827', light='#ffffff', border=2)

    session['pending_totp_secret'] = secret
    return jsonify({
        'success': True,
        'secret': secret,
        'otpauth_uri': uri,
        'qr_svg': qr_svg,
    }), 200


# ── PR #29: per-user station diff feed ────────────────────────────────────

SNAPSHOT_RADIUS_KM = 15.0
SNAPSHOT_RADIUS_MIN_KM = 1.0
SNAPSHOT_RADIUS_MAX_KM = 50.0
SNAPSHOT_DEFAULT_LIMIT = 9


def _compute_snapshot_payload(user: 'User', radius_km: float = SNAPSHOT_RADIUS_KM):
    """Run find_nearest_stations around the user's saved location and
    return (centre_lat, centre_lng, stations_list) suitable for
    serialising into UserStationSnapshot.stations_json. None-return when
    the user has no saved location yet.
    """
    if user.last_location_lat is None or user.last_location_lng is None:
        return None
    from queries import find_nearest_stations
    result = find_nearest_stations(
        user.last_location_lat, user.last_location_lng,
        max_distance=radius_km,
        limit=None,
    )
    return (user.last_location_lat, user.last_location_lng,
            result.get('stations', []))


def _station_key(st: dict) -> str:
    """Stable identity of a BTS row within a snapshot. basestation_id can
    be null in the dataset, so fall back to (lat, lng, provider) when
    missing."""
    bid = st.get('basestation_id')
    if bid:
        return str(bid).upper()
    return f"{st.get('latitude'):.6f},{st.get('longitude'):.6f},{st.get('service_provider') or '-'}"


def compute_snapshot_diff(prev: list[dict], curr: list[dict]) -> dict:
    """Compare two snapshot station lists; return added / removed /
    band_changed sub-lists."""
    prev_by_id = {_station_key(s): s for s in prev}
    curr_by_id = {_station_key(s): s for s in curr}

    added = [curr_by_id[k] for k in curr_by_id.keys() - prev_by_id.keys()]
    removed = [prev_by_id[k] for k in prev_by_id.keys() - curr_by_id.keys()]
    band_changed = []
    for k in curr_by_id.keys() & prev_by_id.keys():
        prev_bands = set(prev_by_id[k].get('frequency_bands') or [])
        curr_bands = set(curr_by_id[k].get('frequency_bands') or [])
        if prev_bands != curr_bands:
            band_changed.append({
                'station': curr_by_id[k],
                'added_bands': sorted(curr_bands - prev_bands),
                'removed_bands': sorted(prev_bands - curr_bands),
            })
    return {'added': added, 'removed': removed, 'band_changed': band_changed}


def take_snapshot():
    """POST /account/snapshot — capture a fresh snapshot at the user's
    saved location. Idempotent-ish: will record a new snapshot every
    call (rate-limited to 6/hour) so the user can force a refresh after
    importing a new stations.db. Long-term this endpoint is also the
    hook the monthly refresh job will call on behalf of each user.

    Accepts JSON `{radius_km: float}` — clamped to [1, 50]. Default 15.
    Rural users (Bieszczady etc.) need a wider radius than urban users
    to get a meaningful sample.
    """
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='take_snapshot').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    raw_radius = body.get('radius_km')
    radius = SNAPSHOT_RADIUS_KM
    if raw_radius is not None:
        try:
            radius = float(raw_radius)
        except (TypeError, ValueError):
            return jsonify({'error': 'radius_km must be a number'}), 400
        if radius < SNAPSHOT_RADIUS_MIN_KM or radius > SNAPSHOT_RADIUS_MAX_KM:
            return jsonify({
                'error': f'radius_km must be between {SNAPSHOT_RADIUS_MIN_KM} and {SNAPSHOT_RADIUS_MAX_KM}',
            }), 400

    payload = _compute_snapshot_payload(user, radius_km=radius)
    if payload is None:
        return jsonify({
            'error': 'No saved location yet — click the map once while logged in.',
        }), 400
    centre_lat, centre_lng, stations = payload

    import json as _json
    snap = UserStationSnapshot(
        user_id=user.id,
        centre_lat=centre_lat,
        centre_lng=centre_lng,
        radius_km=radius,
        stations_json=_json.dumps(stations),
    )
    _db().session.add(snap)
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("take_snapshot commit failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not save snapshot'}), 500
    _audit('snapshot.taken', user.id, {
        'radius_km': radius,
        'count': len(stations),
    })
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
    return jsonify({
        'success': True,
        'snapshot_id': snap.id,
        'count': len(stations),
        'taken_at': snap.taken_at.isoformat() + 'Z',
    }), 200


def changes_page():
    """GET /account/changes — render the diff between the user's two most
    recent snapshots (or 'no changes yet' placeholder). Light-weight: no
    pagination, last-2 only; we can expand to history later if someone
    asks."""
    user, err = _current_user_or_401()
    if err:
        return err

    import json as _json
    snaps = (UserStationSnapshot.query
             .filter_by(user_id=user.id)
             .order_by(UserStationSnapshot.taken_at.desc())
             .limit(2)
             .all())

    if not snaps:
        return render_template('account_changes.html', user=user,
                               snapshots=[], diff=None)

    curr = _json.loads(snaps[0].stations_json)
    if len(snaps) == 1:
        # Only one snapshot → nothing to diff against yet.
        return render_template('account_changes.html', user=user,
                               snapshots=snaps, diff=None,
                               current_count=len(curr))

    prev = _json.loads(snaps[1].stations_json)
    diff = compute_snapshot_diff(prev, curr)
    return render_template('account_changes.html', user=user,
                           snapshots=snaps, diff=diff,
                           current_count=len(curr))


# ── PR #30: multiple named user locations + per-location snapshots ────────

_MAX_LOCATIONS_PER_USER = 20
_LOC_NAME_MAX = 80
_LOC_DESC_MAX = 255
_LOC_RADIUS_MIN_KM = 0.0   # PR #46.9: 0 = "exact spot" alert mode (was 1.0)
_LOC_RADIUS_MAX_KM = 50.0
_LOC_RADIUS_DEFAULT_KM = 0.0  # PR #46.9: was 15 km — too noisy in cities


def _coords_in_pl_bounds(lat: float, lng: float) -> bool:
    """PL bounds with the same ±5 km buffer used by app._coords_in_bounds.
    Lazy-import (instead of a module-level import) so this blueprint can
    still load if app.py changes signature in a future PR."""
    try:
        from app import _coords_in_bounds
        return _coords_in_bounds(lat, lng)
    except Exception:
        return 48.95 <= lat <= 55.55 and 13.95 <= lng <= 24.25


def _serialize_location(loc: UserLocation) -> dict:
    return {
        'id': loc.id,
        'name': loc.name,
        'description': loc.description,
        'lat': loc.lat,
        'lng': loc.lng,
        'radius_km': loc.radius_km,
        'alerting_enabled': bool(loc.alerting_enabled),
        'created_at': loc.created_at.isoformat() + 'Z',
        'updated_at': (loc.updated_at.isoformat() + 'Z') if loc.updated_at else None,
    }


def _location_for_user_or_404(user: User, loc_id: int) -> UserLocation | None:
    loc = _db().session.get(UserLocation, loc_id)
    if loc is None or loc.user_id != user.id:
        return None
    return loc


def _parse_location_payload(payload, *, partial: bool):
    """Pull (name, description, lat, lng, radius_km, alerting_enabled) out
    of the request body, validating types/lengths/bounds. Returns
    (parsed_dict, error_response_or_none). For `partial=True` (update),
    fields absent from the payload are not included in the dict — the
    caller only writes what was sent."""
    out: dict = {}

    if 'name' in payload:
        name = (payload.get('name') or '').strip()
        if not name:
            return None, (jsonify({'error': 'name is required'}), 400)
        if len(name) > _LOC_NAME_MAX:
            return None, (jsonify({'error': 'name too long'}), 400)
        out['name'] = name
    elif not partial:
        return None, (jsonify({'error': 'name is required'}), 400)

    if 'description' in payload:
        desc = (payload.get('description') or '').strip() or None
        if desc and len(desc) > _LOC_DESC_MAX:
            return None, (jsonify({'error': 'description too long'}), 400)
        out['description'] = desc

    has_lat = 'lat' in payload
    has_lng = 'lng' in payload
    if has_lat != has_lng:
        return None, (jsonify({'error': 'lat and lng must be sent together'}), 400)
    if has_lat and has_lng:
        try:
            lat = float(payload.get('lat'))
            lng = float(payload.get('lng'))
        except (TypeError, ValueError):
            return None, (jsonify({'error': 'lat and lng must be numbers'}), 400)
        if not _coords_in_pl_bounds(lat, lng):
            return None, (jsonify({'error': 'Coordinates outside supported area'}), 400)
        out['lat'] = lat
        out['lng'] = lng
    elif not partial:
        return None, (jsonify({'error': 'lat and lng are required'}), 400)

    if 'radius_km' in payload:
        try:
            radius = float(payload.get('radius_km'))
        except (TypeError, ValueError):
            return None, (jsonify({'error': 'radius_km must be a number'}), 400)
        if radius < _LOC_RADIUS_MIN_KM or radius > _LOC_RADIUS_MAX_KM:
            return None, (jsonify({
                'error': f'radius_km must be between {_LOC_RADIUS_MIN_KM} and {_LOC_RADIUS_MAX_KM}',
            }), 400)
        out['radius_km'] = radius

    if 'alerting_enabled' in payload:
        raw = payload.get('alerting_enabled')
        if isinstance(raw, bool):
            out['alerting_enabled'] = raw
        elif isinstance(raw, str):
            out['alerting_enabled'] = raw.strip().lower() in ('1', 'true', 'yes', 'on')
        else:
            out['alerting_enabled'] = bool(raw)

    return out, None


def create_location():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='create_location').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err

    payload = request.get_json(silent=True) or request.form
    parsed, perr = _parse_location_payload(payload, partial=False)
    if perr is not None:
        return perr

    existing = UserLocation.query.filter_by(user_id=user.id).count()
    if existing >= _MAX_LOCATIONS_PER_USER:
        return jsonify({
            'error': f'Location limit reached ({_MAX_LOCATIONS_PER_USER}). Delete one first.',
        }), 400

    loc = UserLocation(
        user_id=user.id,
        name=parsed['name'],
        description=parsed.get('description'),
        lat=parsed['lat'],
        lng=parsed['lng'],
        radius_km=parsed.get('radius_km', _LOC_RADIUS_DEFAULT_KM),
        alerting_enabled=parsed.get('alerting_enabled', True),
    )
    _db().session.add(loc)
    try:
        _db().session.flush()  # need loc.id for the audit meta
    except Exception:
        _db().session.rollback()
        logger.exception("create_location flush failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not create location'}), 500
    _audit('location.created', user.id, {
        'name': loc.name, 'location_id': loc.id,
        'radius_km': loc.radius_km,
        'alerting_enabled': bool(loc.alerting_enabled),
    })
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("create_location commit failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not create location'}), 500

    try:
        _snap, _stations = _capture_location_snapshot(user, loc)
        _audit('snapshot.taken', user.id, {
            'location_id': loc.id, 'radius_km': loc.radius_km,
            'count': len(_stations), 'initial': True,
        })
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("initial snapshot failed for loc_id=%s", loc.id)

    return jsonify({'success': True, 'location': _serialize_location(loc)}), 200


def get_location(loc_id: int):
    user, err = _current_user_or_401()
    if err:
        return err
    loc = _location_for_user_or_404(user, loc_id)
    if loc is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'success': True, 'location': _serialize_location(loc)}), 200


def update_location(loc_id: int):
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='update_location').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err
    loc = _location_for_user_or_404(user, loc_id)
    if loc is None:
        return jsonify({'error': 'Not found'}), 404

    payload = request.get_json(silent=True) or request.form
    parsed, perr = _parse_location_payload(payload, partial=True)
    if perr is not None:
        return perr
    if not parsed:
        return jsonify({'error': 'no fields to update'}), 400

    changed: list[str] = []
    for field, val in parsed.items():
        if getattr(loc, field) != val:
            setattr(loc, field, val)
            changed.append(field)

    _audit('location.updated', user.id, {
        'location_id': loc.id, 'fields': changed,
    })
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("update_location commit failed for loc_id=%s", loc_id)
        return jsonify({'error': 'Could not save location'}), 500
    return jsonify({'success': True, 'location': _serialize_location(loc)}), 200


def delete_location(loc_id: int):
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='delete_location').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err
    loc = _location_for_user_or_404(user, loc_id)
    if loc is None:
        return jsonify({'error': 'Not found'}), 404

    name = loc.name  # capture before delete
    try:
        _db().session.delete(loc)  # cascades to user_station_snapshot
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("delete_location commit failed for loc_id=%s", loc_id)
        return jsonify({'error': 'Could not delete location'}), 500
    _audit('location.deleted', user.id, {'location_id': loc_id, 'name': name})
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
    return jsonify({'success': True}), 200


def _capture_location_snapshot(user, loc):
    """Stage (no commit) a baseline snapshot of the stations a saved location
    currently surfaces, mirroring the map's display query so it reflects what
    the user saw: a positive radius captures everything inside it; radius 0
    (the default 'exact spot') captures the nearest SNAPSHOT_DEFAULT_LIMIT the
    click showed. Returns (snapshot, stations)."""
    from queries import find_nearest_stations
    import json as _json
    if loc.radius_km and loc.radius_km > 0:
        result = find_nearest_stations(
            loc.lat, loc.lng, max_distance=loc.radius_km, limit=None,
        )
    else:
        result = find_nearest_stations(
            loc.lat, loc.lng, limit=SNAPSHOT_DEFAULT_LIMIT,
        )
    stations = result.get('stations', []) if result else []
    snap = UserStationSnapshot(
        user_id=user.id,
        user_location_id=loc.id,
        centre_lat=loc.lat,
        centre_lng=loc.lng,
        radius_km=loc.radius_km,
        stations_json=_json.dumps(stations),
    )
    _db().session.add(snap)
    return snap, stations


def take_location_snapshot(loc_id: int):
    """POST /account/locations/<id>/snapshot — capture a fresh snapshot
    scoped to the given UserLocation. Mirrors the legacy /account/snapshot
    semantics but pulls centre + radius from the UserLocation row instead
    of User.last_location_*. Tagged with `user_location_id` so
    /account/locations/<id>/changes can scope its diff to this location."""
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='take_location_snapshot').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err
    loc = _location_for_user_or_404(user, loc_id)
    if loc is None:
        return jsonify({'error': 'Not found'}), 404

    snap, stations = _capture_location_snapshot(user, loc)
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("take_location_snapshot commit failed for loc_id=%s", loc_id)
        return jsonify({'error': 'Could not save snapshot'}), 500
    _audit('snapshot.taken', user.id, {
        'location_id': loc.id,
        'radius_km': loc.radius_km,
        'count': len(stations),
    })
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
    return jsonify({
        'success': True,
        'snapshot_id': snap.id,
        'count': len(stations),
        'taken_at': snap.taken_at.isoformat() + 'Z',
    }), 200


def location_changes_page(loc_id: int):
    """GET /account/locations/<id>/changes — diff of the two most recent
    snapshots scoped to this location. Same render contract as
    /account/changes but the snapshot query is filtered on
    user_location_id so each saved location has its own independent feed."""
    user, err = _current_user_or_401()
    if err:
        return err
    loc = _location_for_user_or_404(user, loc_id)
    if loc is None:
        return jsonify({'error': 'Not found'}), 404

    import json as _json
    snaps = (UserStationSnapshot.query
             .filter_by(user_id=user.id, user_location_id=loc.id)
             .order_by(UserStationSnapshot.taken_at.desc())
             .limit(2)
             .all())

    if not snaps:
        return render_template('account_location_changes.html',
                               user=user, location=loc,
                               snapshots=[], diff=None)

    curr = _json.loads(snaps[0].stations_json)
    if len(snaps) == 1:
        return render_template('account_location_changes.html',
                               user=user, location=loc,
                               snapshots=snaps, diff=None,
                               current_count=len(curr))

    prev = _json.loads(snaps[1].stations_json)
    diff = compute_snapshot_diff(prev, curr)
    return render_template('account_location_changes.html',
                           user=user, location=loc,
                           snapshots=snaps, diff=diff,
                           current_count=len(curr))
