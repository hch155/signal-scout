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
    session.pop('user_id', None)
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
