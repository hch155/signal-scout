"""Regression coverage for re-audit batch PR C:
- M-NEW-3: TOTP code replay defence — same code accepted at most once
  within the validity window.
"""
from __future__ import annotations

import json as _json
import secrets

import pyotp
import pytest


def _setup_user_with_2fa(authed_client, csrf_token, app):
    """Plant a known TOTP secret on the authed user, enable 2FA. Returns
    (user_id, totp_secret_b32)."""
    from database import db
    from models import User
    from auth_routes import _wrap_totp_secret

    secret = pyotp.random_base32()
    with app.app_context():
        u = User.query.first()
        u.totp_secret_enc = _wrap_totp_secret(secret)
        u.totp_secret = None
        u.totp_enabled = True
        u.last_totp_code = None
        u.last_totp_code_at = None
        db.session.commit()
        return u.id, secret


def test_totp_replay_within_window_is_refused(authed_client, csrf_token, app):
    """First /login/totp with a freshly-generated code succeeds; second
    call with the SAME code (same timestep) is refused. Pre-fix the
    second call would also pass — pure verifier check, no memo of
    last-used code."""
    user_id, secret = _setup_user_with_2fa(authed_client, csrf_token, app)
    code = pyotp.TOTP(secret).now()

    def login_with_code() -> int:
        c = app.test_client()
        with c.session_transaction() as s:
            s["_csrf_token"] = csrf_token
            s["pending_2fa_user_id"] = user_id
        r = c.post("/login/totp",
                   data=_json.dumps({"code": code}),
                   content_type="application/json",
                   headers={"X-CSRF-Token": csrf_token,
                            "Referer": "http://localhost/"})
        return r.status_code

    first = login_with_code()
    second = login_with_code()

    assert first == 200, f"first totp login should succeed, got {first}"
    assert second == 401, (
        f"second login with same code should be refused (got {second}). "
        "M-NEW-3 replay protection regressed — TOTP code is reusable "
        "within its validity window."
    )


def test_totp_different_codes_both_accepted_in_sequence(
        authed_client, csrf_token, app):
    """Sanity: replay protection only blocks the *same* code, not all
    subsequent codes. Two successive logins using two distinct codes
    must both pass (even if rate-limited at a higher level)."""
    user_id, secret = _setup_user_with_2fa(authed_client, csrf_token, app)
    code_a = "123456"  # arbitrary wrong code
    code_b = pyotp.TOTP(secret).now()

    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf_token"] = csrf_token
        s["pending_2fa_user_id"] = user_id
    # First call: a wrong code (so replay state is NOT stamped).
    r_bad = c.post("/login/totp",
                   data=_json.dumps({"code": code_a}),
                   content_type="application/json",
                   headers={"X-CSRF-Token": csrf_token,
                            "Referer": "http://localhost/"})
    assert r_bad.status_code == 401

    # Reset pending state for the second call (the wrong-code branch
    # may have cleared it).
    with c.session_transaction() as s:
        s["_csrf_token"] = csrf_token
        s["pending_2fa_user_id"] = user_id
    r_good = c.post("/login/totp",
                    data=_json.dumps({"code": code_b}),
                    content_type="application/json",
                    headers={"X-CSRF-Token": csrf_token,
                             "Referer": "http://localhost/"})
    assert r_good.status_code == 200, (
        f"valid code after a wrong attempt should succeed, got {r_good.status_code}: "
        f"{r_good.data!r}"
    )
