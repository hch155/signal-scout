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

import logging
import re
from datetime import datetime, date

from flask import Blueprint, jsonify, render_template, request, session

from models import User


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
        session.clear()
        session['_csrf_token'] = preserved_csrf
        session['user_id'] = user.id
        return jsonify({
            "success": True,
            "message": "Logged in successfully.",
            "csrf_token": preserved_csrf,
        }), 200
    else:
        _login_failures_total().inc()
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
    session.clear()
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
    return render_template('account.html', user=user)


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

    full_name = (payload.get('full_name') or '').strip() or None
    bio = (payload.get('bio') or '').strip() or None
    profile_picture = (payload.get('profile_picture') or '').strip() or None
    dob_raw = (payload.get('date_of_birth') or '').strip() or None

    if full_name and len(full_name) > _MAX_NAME_LEN:
        return jsonify({'error': 'full_name too long'}), 400
    if bio and len(bio) > _MAX_BIO_LEN:
        return jsonify({'error': 'bio too long'}), 400
    if profile_picture:
        if len(profile_picture) > _MAX_URL_LEN:
            return jsonify({'error': 'profile_picture URL too long'}), 400
        # Only allow https:// URLs — http or javascript: would be a XSS vector
        # if rendered as <img src=...>. Restrict scheme at the boundary.
        if not profile_picture.lower().startswith('https://'):
            return jsonify({'error': 'profile_picture must be an https:// URL'}), 400

    parsed_dob: date | None = None
    if dob_raw:
        try:
            parsed_dob = datetime.strptime(dob_raw, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'date_of_birth must be YYYY-MM-DD'}), 400
        if parsed_dob > date.today():
            return jsonify({'error': 'date_of_birth cannot be in the future'}), 400

    user.full_name = full_name
    user.bio = bio
    user.profile_picture = profile_picture
    user.date_of_birth = parsed_dob
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
