"""Regression coverage for re-audit batch PR J:
- TOTP brute-force gate: failed /login/totp attempts now route
  through _record_failed_password_attempt so the same atomic
  lockout helper (LOCKOUT_THRESHOLD = 5) covers TOTP guessing.
"""
from __future__ import annotations

import json as _json
from datetime import datetime

import pyotp


def _setup_user_with_2fa(app):
    from database import db
    from models import User
    from auth_routes import _wrap_totp_secret

    secret = pyotp.random_base32()
    with app.app_context():
        u = User.query.first()
        u.totp_secret_enc = _wrap_totp_secret(secret)
        u.totp_secret = None
        u.totp_enabled = True
        u.failed_login_attempts = 0
        u.locked_until = None
        u.last_totp_code = None
        u.last_totp_code_at = None
        db.session.commit()
        return u.id, secret


def test_wrong_totp_increments_lockout_counter(authed_client, csrf_token, app):
    """Each wrong /login/totp attempt must bump
    failed_login_attempts via the atomic helper. Pre-fix the counter
    only ever moved on /login (password) and /account/* bcrypt
    failures, so TOTP brute-force was effectively rate-limited only
    by Flask-Limiter (10/min/IP × 2 instances)."""
    from models import User

    user_id, _secret = _setup_user_with_2fa(app)

    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf_token"] = csrf_token
        s["pending_2fa_user_id"] = user_id
        s["pending_2fa_started_at"] = datetime.utcnow().isoformat()

    for _ in range(3):
        r = c.post("/login/totp",
                   data=_json.dumps({"code": "000000"}),
                   content_type="application/json",
                   headers={"X-CSRF-Token": csrf_token,
                            "Referer": "http://localhost/"})
        assert r.status_code in (401, 403)

    with app.app_context():
        u = User.query.get(user_id)
        assert u.failed_login_attempts >= 3, (
            f"counter is {u.failed_login_attempts}, expected >= 3 — "
            "TOTP failures aren't bumping the shared lockout helper."
        )


def test_repeated_wrong_totp_locks_account(authed_client, csrf_token, app):
    """Crossing LOCKOUT_THRESHOLD on /login/totp must trip the same
    user.locked_until lock that /login already enforces. Subsequent
    bcrypt-using endpoints should refuse via _is_locked()."""
    from models import User
    from auth_routes import LOCKOUT_THRESHOLD

    user_id, _secret = _setup_user_with_2fa(app)

    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf_token"] = csrf_token
        s["pending_2fa_user_id"] = user_id
        s["pending_2fa_started_at"] = datetime.utcnow().isoformat()

    for _ in range(LOCKOUT_THRESHOLD + 1):
        c.post("/login/totp",
                   data=_json.dumps({"code": "000000"}),
                   content_type="application/json",
                   headers={"X-CSRF-Token": csrf_token,
                            "Referer": "http://localhost/"})

    with app.app_context():
        u = User.query.get(user_id)
        assert u.failed_login_attempts >= LOCKOUT_THRESHOLD
        assert u.locked_until is not None
        assert u.locked_until > datetime.utcnow()


def test_correct_totp_clears_failed_attempts_via_existing_login_path(
        authed_client, csrf_token, app):
    """Sanity guard: this PR doesn't touch the success path. After
    LOCKOUT_THRESHOLD - 1 failed TOTP attempts the legit code should
    still authenticate (and the existing /login success-path on next
    login resets failed_login_attempts; not asserted here)."""
    from auth_routes import LOCKOUT_THRESHOLD

    user_id, secret = _setup_user_with_2fa(app)

    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf_token"] = csrf_token
        s["pending_2fa_user_id"] = user_id
        s["pending_2fa_started_at"] = datetime.utcnow().isoformat()

    # One short of lockout.
    for _ in range(LOCKOUT_THRESHOLD - 1):
        c.post("/login/totp",
               data=_json.dumps({"code": "000000"}),
               content_type="application/json",
               headers={"X-CSRF-Token": csrf_token,
                        "Referer": "http://localhost/"})

    # Now the right code: should authenticate.
    with c.session_transaction() as s:
        s["_csrf_token"] = csrf_token
        s["pending_2fa_user_id"] = user_id
        s["pending_2fa_started_at"] = datetime.utcnow().isoformat()
    r = c.post("/login/totp",
               data=_json.dumps({"code": pyotp.TOTP(secret).now()}),
               content_type="application/json",
               headers={"X-CSRF-Token": csrf_token,
                        "Referer": "http://localhost/"})
    assert r.status_code == 200, r.data
