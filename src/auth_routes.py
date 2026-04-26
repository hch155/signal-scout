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
# PR #47: Stripe-style hashed API keys. Both helpers are pure functions
# (no Flask context, no DB) so importing them at module level is safe.
from api_access import hash_api_key, format_api_key_prefix
# PR #44: register / first-key funnel counters. Imported directly because
# they're plain Counters with no circular-import risk.
from observability import (
    funnel_register_started_total,
    funnel_register_completed_total,
    funnel_first_api_key_created_total,
)


logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


# These are filled in by register_auth_routes(); kept module-level so route
# handlers can use them without a closure.
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


# PR #26: account lockout config. After this many wrong-password attempts
# in a row, the account is locked for LOCKOUT_DURATION. Counter resets on
# successful login (any path — password OR password+TOTP). Window matches
# typical industry baselines (5/15min — long enough to deter brute-force,
# short enough that a real user who fat-fingered isn't locked out
# overnight).
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = timedelta(minutes=15)


# ── PR #39: KMS-wrapped TOTP secret ─────────────────────────────────────
# Helpers route every TOTP secret read/write through get_kms() so flipping
# GCP_KMS_KEY_NAME on Cloud Run env switches the storage format without
# touching route code. Wire format on disk: base64(KMS_ciphertext) so a
# TEXT column holds binary safely.

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
    # X-Forwarded-For is a comma-separated list ('client, proxy1, proxy2').
    # Take the first hop = client; rest are infrastructure.
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
    # IPv6: keep top 48 bits, zero the rest. ipaddress.ip_network handles
    # the math cleanly.
    net = ipaddress.ip_network(f"{ip}/48", strict=False)
    return str(net.network_address)


def _audit(event_type: str, user_id: int, meta: dict | None = None) -> None:
    """Record a security-sensitive action against `user_id`. Caller is
    responsible for committing the txn — we add the row to the session so
    it lands atomically with whatever business write triggered it."""
    try:
        raw_ip = (request.headers.get('X-Forwarded-For')
                  or request.remote_addr or '')
        ev = AuditEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=_redact_ip(raw_ip)[:64],
            user_agent=(request.headers.get('User-Agent') or '')[:256],
            meta_json=json.dumps(meta) if meta else None,
        )
        _db().session.add(ev)
    except Exception:
        # Audit is best-effort — never let a failed log break the user-facing
        # action. Log+continue.
        logger.exception("Failed to record audit event %s for user_id=%s",
                         event_type, user_id)


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

    # Apply rate limits via wrapper since blueprint can't decorate at
    # registration time without ordering pain.
    auth_bp.add_url_rule("/register", endpoint="register",
                         view_func=limiter.limit("5 per hour")(register_user),
                         methods=["POST"])
    # PR #26: bumped from 3/min to 10/min. Per-IP rate limit was defending
    # against slow per-account brute-force; that job now belongs to
    # the per-account lockout (5 wrong → 15-min freeze). Higher per-IP
    # cap means a real user typing a wrong password 4× isn't immediately
    # 429'd, while the account itself still locks out attackers.
    auth_bp.add_url_rule("/login", endpoint="login",
                         view_func=limiter.limit("10 per minute")(login_user),
                         methods=["POST"])
    auth_bp.add_url_rule("/logout", endpoint="logout",
                         view_func=logout, methods=["POST"])
    auth_bp.add_url_rule("/session_check", endpoint="session_check",
                         view_func=session_check, methods=["GET"])
    auth_bp.add_url_rule("/account", endpoint="account_page",
                         view_func=account_page, methods=["GET"])
    auth_bp.add_url_rule("/account/regenerate_api_key",
                         endpoint="regenerate_api_key",
                         view_func=limiter.limit("3 per hour")(regenerate_api_key),
                         methods=["POST"])
    # PR #12: profile + password + delete. Tighter limit on /password and
    # /delete because both are credential operations; profile updates are
    # benign so they get a looser limit (still capped to discourage scrape).
    auth_bp.add_url_rule("/account/profile", endpoint="update_profile",
                         view_func=limiter.limit("20 per hour")(update_profile),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/password", endpoint="change_password",
                         view_func=limiter.limit("5 per hour")(change_password),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/delete", endpoint="delete_account",
                         view_func=limiter.limit("3 per hour")(delete_account),
                         methods=["POST"])
    # PR #14: multi-key API. Create/revoke are rate-limited to discourage
    # the "spray ten keys to find one that bypasses a per-tier limit" pattern.
    auth_bp.add_url_rule("/account/keys", endpoint="create_api_key",
                         view_func=limiter.limit("10 per hour")(create_api_key),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/keys/<int:key_id>/revoke",
                         endpoint="revoke_api_key",
                         view_func=limiter.limit("20 per hour")(revoke_api_key),
                         methods=["POST"])
    # PR #16: 2FA TOTP. Start/verify/disable + the second-step login
    # verification after a correct password.
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
    # PR #25: rotate the TOTP secret without disabling 2FA outright. Same
    # contract as setup → returns secret + QR + new recovery codes — but
    # only callable when 2FA is currently enabled and only after password
    # confirmation. Old secret + recovery codes invalidated atomically on
    # totp_verify success.
    auth_bp.add_url_rule("/account/2fa/regenerate", endpoint="totp_regenerate",
                         view_func=limiter.limit("5 per hour")(totp_regenerate),
                         methods=["POST"])
    # PR #29: per-user station diff feed.
    auth_bp.add_url_rule("/account/snapshot", endpoint="take_snapshot",
                         view_func=limiter.limit("6 per hour")(take_snapshot),
                         methods=["POST"])
    auth_bp.add_url_rule("/account/changes", endpoint="changes_page",
                         view_func=changes_page, methods=["GET"])
    # PR #30: multiple named saved locations + per-location snapshots.
    # Rate limits sized so a normal user (≤20 locations cap) cannot trip
    # them in normal use, while bulk script abuse is rejected. Snapshot
    # is the heaviest (runs find_nearest_stations) — kept tightest.
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


# ── View functions ──────────────────────────────────────────────────────────

def register_user():
    # PR #44 funnel step 1: every register attempt counts (success and
    # failure both — we want the success-rate ratio to reflect reality,
    # including bot traffic that hits the page and fails on validation).
    funnel_register_started_total.inc()
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='register').inc()
        return jsonify({'error': 'Invalid request'}), 403

    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if not email or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return "Invalid email address.", 400

    if not password or not re.fullmatch(
        r"(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[^\w\s]).{8,64}$", password
    ):
        return "Password does not meet criteria.", 400

    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match.'}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user is not None:
        return 'Email already registered.'

    hashed_password = _bcrypt().generate_password_hash(password).decode('utf-8')

    try:
        # PR #47: hash-on-create. The auto-generated registration key is
        # stored as sha256(raw)+prefix only — we never persist the
        # plaintext. Side-effect: the user does not get a directly-usable
        # token at signup; they create one explicitly from /account
        # (one-shot reveal). This matches Stripe / GitHub UX and removes
        # the "DB compromise leaks every API key" failure mode.
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
        # PR #44 funnel step 2: register completed (HTTP 200 path).
        funnel_register_completed_total.inc()
        return jsonify({"success": True, "message": "User registered successfully."}), 200
    except Exception:
        _db().session.rollback()
        logger.exception("Error registering user")
        return jsonify({"success": False, "message": "Registration failed due to a server error."}), 500


def login_user():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='login').inc()
        return jsonify({'error': 'Invalid request'}), 403

    email = request.form.get('email')
    password = request.form.get('password')

    user = User.query.filter_by(email=email).first()

    # PR #26: account lockout. If the user is currently locked, bounce
    # without spending a bcrypt round (cheap defence; brute-forcer can't
    # use the locked account as a pollard for distinguishing valid emails
    # via timing). 403 + how-long.
    if user is not None and user.locked_until is not None:
        if user.locked_until > datetime.utcnow():
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
        # Lockout window expired — clear the stamp and let the request
        # proceed normally. Counter is cleared on the success path; if
        # this attempt also fails, it counts toward a fresh lock.
        user.locked_until = None

    if user and _bcrypt().check_password_hash(user.password_hash, password):
        # Successful auth — reset lockout state.
        user.failed_login_attempts = 0
        user.locked_until = None

        # Audit fix (High — CSRF token survives privilege boundary):
        # rotate the CSRF token across session.clear(). Pre-login the
        # token may have been captured by an attacker; if we kept it,
        # the same token would authorize POSTs from the now-logged-in
        # session. The new token goes back to the client in the JSON
        # response, so the AJAX caller can update its meta tag for
        # the next POST.
        import secrets
        new_csrf = secrets.token_hex(32)

        # PR #16: if the user has 2FA enabled, password alone is not enough.
        # Park the user_id in a half-session bucket and require a TOTP code
        # at /login/totp before graduating to a real logged-in session.
        if user.totp_enabled:
            session.clear()
            session['_csrf_token'] = new_csrf
            session['pending_2fa_user_id'] = user.id
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
        if user is not None:
            # PR #26: bump counter; lock if past threshold.
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            audit_meta: dict = {"reason": "bad_password",
                                "attempts": user.failed_login_attempts}
            if user.failed_login_attempts >= LOCKOUT_THRESHOLD:
                user.locked_until = datetime.utcnow() + LOCKOUT_DURATION
                audit_meta["locked_until"] = user.locked_until.isoformat() + 'Z'
                _audit('account.locked', user.id, audit_meta)
            else:
                _audit('login.fail', user.id, audit_meta)
            try:
                _db().session.commit()
            except Exception:
                _db().session.rollback()
        return jsonify({"success": False, "message": "Invalid email or password."}), 401


def logout():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='logout').inc()
        return jsonify({'error': 'Invalid request'}), 403
    # Full session.clear() (not just session.pop('user_id')) so the next
    # request gets a brand-new CSRF token and any other server-side session
    # state is dropped. Combined with the Cache-Control: no-store header on
    # /account, this closes the "Back-button shows my account after logout"
    # leak.
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
    # PR #47: only auto-mint a default key if the user has neither a
    # legacy plaintext value NOR a hashed one. After hash-on-create
    # (registration), users come in with `api_key=None` but
    # `api_key_hash` set — we must not overwrite that, otherwise we'd
    # invalidate the hash they were issued at signup.
    if not user.api_key and not user.api_key_hash:
        raw_key = _generate_api_key()
        user.api_key_hash = hash_api_key(raw_key)
        user.api_key_prefix = format_api_key_prefix(raw_key)
        user.api_tier = user.api_tier or 'free'
        _db().session.commit()
    # PR #14: list of named keys for this user, newest first. Active keys
    # first, then revoked ones (history). The legacy User.api_key has its
    # mirrored "default" ApiKey row from the migration; show it the same as
    # any other key.
    api_keys = (ApiKey.query
                .filter_by(user_id=user.id)
                .order_by(ApiKey.revoked_at.is_(None).desc(), ApiKey.created_at.desc())
                .all())
    # PR #15: surface the user's last 20 audit events so they can spot
    # logins they don't recognize, password changes they didn't initiate, etc.
    audit_events = (AuditEvent.query
                    .filter_by(user_id=user.id)
                    .order_by(AuditEvent.created_at.desc())
                    .limit(20)
                    .all())
    # PR #30: list of named saved locations (newest first), shown in a
    # dedicated card on /account with create/edit/delete inline.
    locations = (UserLocation.query
                 .filter_by(user_id=user.id)
                 .order_by(UserLocation.created_at.desc())
                 .all())
    return render_template('account.html', user=user,
                           api_keys=api_keys, audit_events=audit_events,
                           locations=locations)


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
    # PR #47: hash-on-create rotation. Mint raw, store sha256(raw)+prefix
    # only. The legacy plaintext column is cleared in the same txn so a
    # later DB read can't return a stale value alongside the new hash.
    # Raw token is returned in the response — that's the one-shot reveal
    # the /account UI surfaces in its yellow callout banner.
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

    # PR #19 / PR #36: only-update-fields-present semantics. The simplified
    # /account UI sends just `company` and the legacy free-text profile
    # columns (full_name/bio/profile_picture/date_of_birth) were dropped
    # in PR #36 — `company` is the only writable profile field now.
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

    payload = request.get_json(silent=True) or request.form
    current = payload.get('current_password') or ''
    new = payload.get('new_password') or ''
    confirm = payload.get('confirm_password') or ''

    if not _bcrypt().check_password_hash(user.password_hash, current):
        # Re-use the login_failures counter so brute-forcing the password
        # change endpoint shows up on the same alert as login brute-forcing.
        _login_failures_total().inc()
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
    # Rotate session as a precaution: a stolen cookie should not survive a
    # password change. Audit fix (High — CSRF privilege boundary): also
    # mint a fresh CSRF token rather than preserving the pre-change one.
    # The new token is returned in the JSON response so the still-open
    # form can update its X-CSRF-Token meta for the success follow-up.
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
    # PR #48.5: security alert email. Best-effort — SendGrid outage
    # must not break the password-change flow. emails._send() already
    # respects user.email_alerts_enabled (silent skip).
    try:
        from emails import send_password_changed
        send_password_changed(user)
    except Exception:
        logger.exception("send_password_changed failed for user_id=%s", user.id)
    return jsonify({'success': True, 'csrf_token': new_csrf}), 200


def delete_account():
    if not _validate_csrf():
        _csrf_failures_total().labels(endpoint='delete_account').inc()
        return jsonify({'error': 'Invalid request'}), 403
    user, err = _current_user_or_401()
    if err:
        return err

    payload = request.get_json(silent=True) or request.form
    confirm_password = payload.get('current_password') or ''
    confirm_phrase = (payload.get('confirm_phrase') or '').strip()

    if not _bcrypt().check_password_hash(user.password_hash, confirm_password):
        _login_failures_total().inc()
        return jsonify({'error': 'Current password is incorrect'}), 401
    # Belt-and-suspenders: typed phrase prevents a single accidental click on
    # a fake confirm dialog from nuking the account.
    if confirm_phrase != 'DELETE':
        return jsonify({'error': "Type DELETE to confirm"}), 400

    user_id = user.id
    try:
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
# Cap on simultaneously-active keys per user. Keeps the /account UI sane and
# discourages key sprawl (each unrevoked key is a leak risk).
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

    # PR #44 funnel step 3: count only the FIRST extra key created by
    # this user (the auto-key minted at registration is not counted —
    # it's a side-effect of registration, not "intent to use the API").
    if ApiKey.query.filter_by(user_id=user.id).count() <= 1:
        funnel_first_api_key_created_total.inc()
    # PR #47: hash-on-create. Persist sha256(raw) + display prefix only;
    # raw token returns in the JSON response as the one-shot reveal the
    # /account UI flashes in its yellow callout banner.
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
        # Same response for not-found and not-owned so a malicious caller
        # can't enumerate other users' key IDs.
        return jsonify({'error': 'Not found'}), 404
    if ak.revoked_at is not None:
        return jsonify({'error': 'Already revoked'}), 400

    from datetime import datetime
    ak.revoked_at = datetime.utcnow()
    # If the user revoked the legacy "default" key (the one mirrored on
    # User.api_key), also clear the column so anyone still reading
    # User.api_key directly sees the same picture. PR #47: also clear
    # the hashed mirror — both pre-PR plaintext and post-PR hash live
    # on User during the back-compat window.
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
# Valid codes allowed ±1 window (30s before/after) to tolerate clock skew.
_TOTP_VALID_WINDOW = 1
_RECOVERY_CODE_COUNT = 10


def _pyotp():
    # Lazy import so the module stays importable if pyotp is absent (unlikely
    # — pinned in requirements.txt — but keeps the blueprint self-contained).
    import pyotp
    return pyotp


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

    # Render the URI as an SVG QR code so the user can scan with their
    # phone instead of typing the secret manually. segno is a pure-Python
    # QR lib (no Pillow); svg_inline() returns an XML string we can drop
    # straight into the page via DOMParser.
    import segno
    qr = segno.make(uri, error='M')
    qr_svg = qr.svg_inline(scale=5, dark='#111827', light='#ffffff', border=2)

    # Park the candidate secret in the session. totp_verify moves it onto
    # the user row after the user proves possession with a valid code.
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

    payload = request.get_json(silent=True) or request.form
    password = payload.get('current_password') or ''
    code = (payload.get('code') or '').strip().replace(' ', '')

    if not _bcrypt().check_password_hash(user.password_hash, password):
        _login_failures_total().inc()
        return jsonify({'error': 'Current password is incorrect'}), 401
    if not _pyotp().TOTP(_unwrap_totp_secret(user)).verify(code, valid_window=_TOTP_VALID_WINDOW):
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
    # PR #48.5: security alert email — disabling 2FA is suspicious if
    # not user-initiated. Best-effort.
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
    user = _db().session.get(User, pending)
    if not user or not user.totp_enabled:
        session.pop('pending_2fa_user_id', None)
        return jsonify({'error': 'No 2FA step in progress'}), 400

    payload = request.get_json(silent=True) or request.form
    code = (payload.get('code') or '').strip().replace(' ', '')

    used_recovery = False
    ok = False
    if code:
        if _pyotp().TOTP(_unwrap_totp_secret(user)).verify(code, valid_window=_TOTP_VALID_WINDOW):
            ok = True
        else:
            # Try as a recovery code: compare against each stored hash.
            import json as _json
            hashes = _json.loads(user.recovery_codes_json or '[]')
            for idx, h in enumerate(list(hashes)):
                if _bcrypt().check_password_hash(h, code):
                    # Single-use: remove that hash from the list.
                    hashes.pop(idx)
                    user.recovery_codes_json = _json.dumps(hashes)
                    ok = True
                    used_recovery = True
                    break

    if not ok:
        _login_failures_total().inc()
        _audit('login.2fa_fail', user.id)
        try:
            _db().session.commit()
        except Exception:
            _db().session.rollback()
        return jsonify({'error': 'Invalid code'}), 401

    # Audit fix (High — CSRF privilege boundary): rotate token across
    # the half-session -> full-session promotion. New token returned
    # in JSON for the AJAX caller to update its meta.
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
    # PR #48.5: when a recovery code was just consumed, alert the user.
    # This is the highest-stakes signal in the auth surface — recovery
    # codes are the last line of defence after losing 2FA, so an
    # unexpected use means the attacker has the password AND a code.
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

    payload = request.get_json(silent=True) or request.form
    password = payload.get('current_password') or ''
    if not _bcrypt().check_password_hash(user.password_hash, password):
        _login_failures_total().inc()
        return jsonify({'error': 'Current password is incorrect'}), 401

    pyotp = _pyotp()
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=_ISSUER)
    import segno
    qr_svg = segno.make(uri, error='M').svg_inline(
        scale=5, dark='#111827', light='#ffffff', border=2)

    # Park as pending — totp_verify swaps it onto the user row when the
    # caller proves they got it into their authenticator.
    session['pending_totp_secret'] = secret
    return jsonify({
        'success': True,
        'secret': secret,
        'otpauth_uri': uri,
        'qr_svg': qr_svg,
    }), 200


# ── PR #29: per-user station diff feed ────────────────────────────────────

# Default snapshot radius if the caller doesn't specify one. 5 km was the
# initial pick but it's too tight in rural areas (Bieszczady, north-east —
# typically 0-3 BTS within 5 km). 15 km covers most of Poland reasonably
# while still keeping payloads compact in cities (~100-200 stations max).
# Caller can override per-snapshot via JSON `radius_km`. Adaptive radius
# (auto-grow until N ≥ 10) is roadmapped.
SNAPSHOT_RADIUS_KM = 15.0
SNAPSHOT_RADIUS_MIN_KM = 1.0
SNAPSHOT_RADIUS_MAX_KM = 50.0


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

# Sanity cap so a single user can't fill the table. Locations are tiny
# (≈80 bytes/row) but each one carries its own snapshot history; 20 is
# generous for the "home / work / parents / cabin" use case while still
# bounding worst-case storage.
_MAX_LOCATIONS_PER_USER = 20
_LOC_NAME_MAX = 80
_LOC_DESC_MAX = 255
# Per-location snapshot radius bounds — same window as the legacy single-
# location snapshot so behaviour matches once a user migrates.
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
        # Fallback to literal bounds (matches src/app.py PL_LAT/LNG_*).
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
        # Same response for not-found and not-owned so a malicious caller
        # can't enumerate other users' location IDs (mirrors the ApiKey
        # ownership pattern).
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

    # lat/lng — both must change together if either is present, since one
    # without the other puts the centre somewhere unintended.
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

    # Hard cap so a single user can't fill the table (and so the
    # /account UI list stays scannable).
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

    from queries import find_nearest_stations
    result = find_nearest_stations(
        loc.lat, loc.lng,
        max_distance=loc.radius_km,
        limit=None,
    )
    stations = result.get('stations', []) if result else []

    import json as _json
    snap = UserStationSnapshot(
        user_id=user.id,
        user_location_id=loc.id,
        centre_lat=loc.lat,
        centre_lng=loc.lng,
        radius_km=loc.radius_km,
        stations_json=_json.dumps(stations),
    )
    _db().session.add(snap)
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
