"""PR #16: 2FA TOTP flows.

Covers setup → verify → enable, login (password OK + TOTP), disable,
recovery codes, and the audit-log entries written for 2FA actions.
"""

import json

import pytest
import pyotp

from models import User, AuditEvent


KNOWN_PW = "Aa1!aaaaaa"


def _enable_2fa(client, csrf_token, app):
    """Helper: walk through setup + verify so the user ends with totp_enabled."""
    setup = client.post("/account/2fa/setup",
                        headers={"X-CSRF-Token": csrf_token})
    assert setup.status_code == 200, setup.data
    secret = setup.get_json()["secret"]

    code = pyotp.TOTP(secret).now()
    verify = client.post("/account/2fa/verify",
                         data=json.dumps({"code": code}),
                         content_type="application/json",
                         headers={"X-CSRF-Token": csrf_token})
    assert verify.status_code == 200, verify.data
    body = verify.get_json()
    assert body["success"] is True
    assert len(body["recovery_codes"]) == 10

    with app.app_context():
        u = User.query.first()
        assert u.totp_enabled is True
        assert u.totp_secret == secret
    return secret, body["recovery_codes"]


# ── Setup + verify ────────────────────────────────────────────────────────

def test_setup_no_csrf_403(authed_client):
    r = authed_client.post("/account/2fa/setup")
    assert r.status_code == 403


def test_setup_anonymous_401(client, csrf_token):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post("/account/2fa/setup", headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401


def test_setup_returns_secret_and_uri(authed_client, csrf_token):
    r = authed_client.post("/account/2fa/setup",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200
    body = r.get_json()
    assert "secret" in body and len(body["secret"]) >= 16
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    # Issuer is encoded in the URI
    assert "signal-scout" in body["otpauth_uri"]
    # PR #25: setup also returns a server-rendered QR (SVG) so the user
    # doesn't have to type the secret manually.
    assert body.get("qr_svg", "").startswith("<svg")


KNOWN_PW_REGEN = "Aa1!aaaaaa"


def test_regenerate_requires_password(authed_client, csrf_token, app):
    _enable_2fa(authed_client, csrf_token, app)
    # No password → 401
    r = authed_client.post("/account/2fa/regenerate",
                           data=json.dumps({"current_password": "WRONG-PW1!"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401
    # Right password → 200 + new secret + qr_svg
    r = authed_client.post("/account/2fa/regenerate",
                           data=json.dumps({"current_password": KNOWN_PW_REGEN}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body["success"] is True
    assert len(body["secret"]) >= 16
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["qr_svg"].startswith("<svg")


def test_regenerate_when_2fa_off_returns_400(authed_client, csrf_token):
    # 2FA not enabled — regenerate should refuse and tell caller to use setup
    r = authed_client.post("/account/2fa/regenerate",
                           data=json.dumps({"current_password": KNOWN_PW_REGEN}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 400


def test_regenerate_no_csrf_403(authed_client):
    r = authed_client.post("/account/2fa/regenerate",
                           data=json.dumps({"current_password": KNOWN_PW_REGEN}),
                           content_type="application/json")
    assert r.status_code == 403


def test_verify_with_wrong_code_fails(authed_client, csrf_token):
    authed_client.post("/account/2fa/setup",
                       headers={"X-CSRF-Token": csrf_token})
    r = authed_client.post("/account/2fa/verify",
                           data=json.dumps({"code": "000000"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401


def test_verify_with_correct_code_enables_2fa(authed_client, csrf_token, app):
    _enable_2fa(authed_client, csrf_token, app)


def test_setup_when_already_enabled_400(authed_client, csrf_token, app):
    _enable_2fa(authed_client, csrf_token, app)
    r = authed_client.post("/account/2fa/setup",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 400


# ── Login flow with 2FA ────────────────────────────────────────────────────

def test_login_with_2fa_requires_totp_code(client, csrf_token, app):
    # Register + login + enable 2FA via the helper
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    email = "twofa-login@example.com"
    client.post("/register", data={
        "_csrf_token": csrf_token, "email": email,
        "password": KNOWN_PW, "confirm_password": KNOWN_PW,
    })
    client.post("/login", data={
        "_csrf_token": csrf_token, "email": email, "password": KNOWN_PW,
    })
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    secret, _ = _enable_2fa(client, csrf_token, app)

    # Logout, then re-login: password alone should NOT graduate to a session
    client.post("/logout", headers={"X-CSRF-Token": csrf_token})
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token

    r = client.post("/login", data={
        "_csrf_token": csrf_token, "email": email, "password": KNOWN_PW,
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("totp_required") is True
    assert body.get("success") is False

    # /session_check should still be logged out
    sc = client.get("/session_check").get_json()
    assert sc == {"logged_in": False}

    # Submit valid TOTP → graduate to a real session
    code = pyotp.TOTP(secret).now()
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r2 = client.post("/login/totp",
                     data=json.dumps({"code": code}),
                     content_type="application/json",
                     headers={"X-CSRF-Token": csrf_token})
    assert r2.status_code == 200, r2.data
    assert r2.get_json()["success"] is True
    sc2 = client.get("/session_check").get_json()
    assert sc2 == {"logged_in": True}


def test_login_totp_with_recovery_code(client, csrf_token, app):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    email = "twofa-rec@example.com"
    client.post("/register", data={
        "_csrf_token": csrf_token, "email": email,
        "password": KNOWN_PW, "confirm_password": KNOWN_PW,
    })
    client.post("/login", data={
        "_csrf_token": csrf_token, "email": email, "password": KNOWN_PW,
    })
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    _, recovery_codes = _enable_2fa(client, csrf_token, app)

    client.post("/logout", headers={"X-CSRF-Token": csrf_token})
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    client.post("/login", data={
        "_csrf_token": csrf_token, "email": email, "password": KNOWN_PW,
    })
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token

    # Use the first recovery code as the second factor
    one_code = recovery_codes[0]
    r = client.post("/login/totp",
                    data=json.dumps({"code": one_code}),
                    content_type="application/json",
                    headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200, r.data
    assert r.get_json()["success"] is True

    # Recovery code is single-use — using it again must fail
    client.post("/logout", headers={"X-CSRF-Token": csrf_token})
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    client.post("/login", data={
        "_csrf_token": csrf_token, "email": email, "password": KNOWN_PW,
    })
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r2 = client.post("/login/totp",
                     data=json.dumps({"code": one_code}),
                     content_type="application/json",
                     headers={"X-CSRF-Token": csrf_token})
    assert r2.status_code == 401


def test_login_totp_without_pending_400(client, csrf_token):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post("/login/totp",
                    data=json.dumps({"code": "123456"}),
                    content_type="application/json",
                    headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 400


# ── Disable ──────────────────────────────────────────────────────────────

def test_disable_requires_both_password_and_code(authed_client, csrf_token, app):
    secret, _ = _enable_2fa(authed_client, csrf_token, app)
    code = pyotp.TOTP(secret).now()

    # Wrong password
    r = authed_client.post("/account/2fa/disable",
                           data=json.dumps({"current_password": "WRONG-PW1!", "code": code}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401

    # Wrong code
    r = authed_client.post("/account/2fa/disable",
                           data=json.dumps({"current_password": KNOWN_PW, "code": "000000"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401

    # Both right → 200, totp_enabled goes False
    r = authed_client.post("/account/2fa/disable",
                           data=json.dumps({"current_password": KNOWN_PW, "code": code}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200
    with app.app_context():
        u = User.query.first()
        assert u.totp_enabled is False
        assert u.totp_secret is None
        assert u.recovery_codes_json is None


# ── Audit hooks ──────────────────────────────────────────────────────────

def test_2fa_enable_disable_writes_audit(authed_client, csrf_token, app):
    secret, _ = _enable_2fa(authed_client, csrf_token, app)
    with app.app_context():
        ev = AuditEvent.query.filter_by(event_type='2fa.enabled').count()
        assert ev == 1

    code = pyotp.TOTP(secret).now()
    authed_client.post("/account/2fa/disable",
                       data=json.dumps({"current_password": KNOWN_PW, "code": code}),
                       content_type="application/json",
                       headers={"X-CSRF-Token": csrf_token})
    with app.app_context():
        assert AuditEvent.query.filter_by(event_type='2fa.disabled').count() == 1
