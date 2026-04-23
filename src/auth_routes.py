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
from datetime import datetime, date

from flask import Blueprint, jsonify, render_template, request, session

from models import User, ApiKey, AuditEvent


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


# ── PR #15: audit log ──────────────────────────────────────────────────────

def _audit(event_type: str, user_id: int, meta: dict | None = None) -> None:
    """Record a security-sensitive action against `user_id`. Caller is
    responsible for committing the txn — we add the row to the session so
    it lands atomically with whatever business write triggered it."""
    try:
        ev = AuditEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=(request.headers.get('X-Forwarded-For')
                        or request.remote_addr or '')[:64],
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
    auth_bp.add_url_rule("/login", endpoint="login",
                         view_func=limiter.limit("3 per minute")(login_user),
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

    app.register_blueprint(auth_bp)


# ── View functions ──────────────────────────────────────────────────────────

def register_user():
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
        user = User(
            email=email,
            password_hash=hashed_password,
            api_key=_generate_api_key(),
            api_tier='free',
        )
        _db().session.add(user)
        _db().session.commit()
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

    if user and _bcrypt().check_password_hash(user.password_hash, password):
        # Rotate session against fixation, preserve CSRF token so the meta
        # tag on the page stays usable for next POST (PR #1 fix).
        import secrets
        preserved_csrf = session.get('_csrf_token') or secrets.token_hex(32)

        # PR #16: if the user has 2FA enabled, password alone is not enough.
        # Park the user_id in a half-session bucket and require a TOTP code
        # at /login/totp before graduating to a real logged-in session.
        if user.totp_enabled:
            session.clear()
            session['_csrf_token'] = preserved_csrf
            session['pending_2fa_user_id'] = user.id
            return jsonify({
                "success": False,
                "totp_required": True,
                "message": "2FA code required.",
                "csrf_token": preserved_csrf,
            }), 200

        session.clear()
        session['_csrf_token'] = preserved_csrf
        session['user_id'] = user.id
        _audit('login.success', user.id)
        try:
            _db().session.commit()
        except Exception:
            _db().session.rollback()
        return jsonify({
            "success": True,
            "message": "Logged in successfully.",
            "csrf_token": preserved_csrf,
        }), 200
    else:
        _login_failures_total().inc()
        if user is not None:
            # We know which account got the failed attempt — log it to the
            # right user's audit trail. Anonymous failures (unknown email)
            # still bump the metric but don't get a per-user row.
            _audit('login.fail', user.id, {"reason": "bad_password"})
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
    if not user.api_key:
        user.api_key = _generate_api_key()
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
    return render_template('account.html', user=user,
                           api_keys=api_keys, audit_events=audit_events)


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
    user.api_key = _generate_api_key()
    _db().session.commit()
    return jsonify({"success": True, "api_key": user.api_key}), 200


# ── PR #12: profile / change password / delete account ─────────────────────

# Conservative bounds on free-text profile fields. Matches the model column
# widths defined in src/models.py and prevents oversized payloads from
# bloating the SQLite row store.
_MAX_NAME_LEN = 100
_MAX_BIO_LEN = 500
_MAX_URL_LEN = 255
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

    # PR #19: switched to "only-update-fields-present" semantics so the
    # simplified UI (company only) doesn't accidentally NULL out legacy
    # profile fields for existing users, and so legacy API clients that
    # POST only the old fields don't NULL out company.
    if 'company' in payload:
        company = (payload.get('company') or '').strip() or None
        if company and len(company) > 120:
            return jsonify({'error': 'company too long'}), 400
        user.company = company

    if 'full_name' in payload:
        full_name = (payload.get('full_name') or '').strip() or None
        if full_name and len(full_name) > _MAX_NAME_LEN:
            return jsonify({'error': 'full_name too long'}), 400
        user.full_name = full_name

    if 'bio' in payload:
        bio = (payload.get('bio') or '').strip() or None
        if bio and len(bio) > _MAX_BIO_LEN:
            return jsonify({'error': 'bio too long'}), 400
        user.bio = bio

    if 'profile_picture' in payload:
        profile_picture = (payload.get('profile_picture') or '').strip() or None
        if profile_picture:
            if len(profile_picture) > _MAX_URL_LEN:
                return jsonify({'error': 'profile_picture URL too long'}), 400
            # Only allow https:// URLs — http or javascript: would be a XSS
            # vector if rendered as <img src=...>. Restrict scheme at the
            # boundary.
            if not profile_picture.lower().startswith('https://'):
                return jsonify({'error': 'profile_picture must be an https:// URL'}), 400
        user.profile_picture = profile_picture

    if 'date_of_birth' in payload:
        dob_raw = (payload.get('date_of_birth') or '').strip() or None
        parsed_dob: date | None = None
        if dob_raw:
            try:
                parsed_dob = datetime.strptime(dob_raw, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'error': 'date_of_birth must be YYYY-MM-DD'}), 400
            if parsed_dob > date.today():
                return jsonify({'error': 'date_of_birth cannot be in the future'}), 400
        user.date_of_birth = parsed_dob

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
    # password change. Preserve the CSRF token so the client's open form keeps
    # working for the success-toast follow-up.
    import secrets
    preserved_csrf = session.get('_csrf_token') or secrets.token_hex(32)
    session.clear()
    session['_csrf_token'] = preserved_csrf
    session['user_id'] = user.id
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("change_password commit failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not save password'}), 500
    return jsonify({'success': True, 'csrf_token': preserved_csrf}), 200


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

    new_key_value = _generate_api_key()
    ak = ApiKey(user_id=user.id, name=name, key=new_key_value)
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
        'key': ak.key,
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
    # User.api_key directly sees the same picture.
    if ak.name == 'default' and user.api_key == ak.key:
        user.api_key = None
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

    # Park the candidate secret in the session. totp_verify moves it onto
    # the user row after the user proves possession with a valid code.
    session['pending_totp_secret'] = secret
    return jsonify({
        'success': True,
        'secret': secret,
        'otpauth_uri': uri,
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
    user.totp_secret = pending
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
    if not _pyotp().TOTP(user.totp_secret).verify(code, valid_window=_TOTP_VALID_WINDOW):
        return jsonify({'error': 'Invalid 2FA code'}), 401

    user.totp_secret = None
    user.totp_enabled = False
    user.recovery_codes_json = None
    _audit('2fa.disabled', user.id)
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
        logger.exception("totp_disable commit failed for user_id=%s", user.id)
        return jsonify({'error': 'Could not save'}), 500
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
        if _pyotp().TOTP(user.totp_secret).verify(code, valid_window=_TOTP_VALID_WINDOW):
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

    import secrets
    preserved_csrf = session.get('_csrf_token') or secrets.token_hex(32)
    session.clear()
    session['_csrf_token'] = preserved_csrf
    session['user_id'] = user.id
    _audit('login.success',
           user.id,
           {'via': 'recovery_code'} if used_recovery else {'via': 'totp'})
    try:
        _db().session.commit()
    except Exception:
        _db().session.rollback()
    return jsonify({
        'success': True,
        'csrf_token': preserved_csrf,
    }), 200
