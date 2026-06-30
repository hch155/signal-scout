"""Regression coverage for the security PRs landed 2026-04-26 / 2026-04-27
(PRs #296-#300 + commit a7e441f). Each test pins a single observable
property of one fix so a future refactor can't silently undo it.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

import pytest


# ──────────────────────────────────────────────────────────────────────
# CSRF rotation across privilege boundary (PR #297 + commit a7e441f)
# ──────────────────────────────────────────────────────────────────────

def test_login_response_includes_rotated_csrf_token(client, csrf_token):
    """The /login JSON response must carry the freshly rotated csrf_token
    so the browser can patch its meta tag — without this, the next POST
    after AJAX login 403s. (Self-audit Real Bug, fixed in a7e441f.)"""
    email = f"csrf-{secrets.token_hex(3)}@example.com"
    password = "Aa1!aaaaaa"
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token

    client.post("/register", data={
        "_csrf_token": csrf_token, "email": email,
        "password": password, "confirm_password": password,
    })
    r = client.post("/login", data={
        "_csrf_token": csrf_token, "email": email, "password": password,
    })
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body.get("success") is True
    token = body.get("csrf_token")
    assert isinstance(token, str) and len(token) == 64, \
        "login must return a 64-char hex csrf_token after session rotation"
    # And it must NOT be the pre-login token the test planted.
    assert token != csrf_token


def test_change_password_response_includes_rotated_csrf_token(authed_client, csrf_token):
    """Same contract on /account/password — already covered by account.js
    flow but the server side is the load-bearing piece."""
    r = authed_client.post(
        "/account/password",
        data={
            "_csrf_token": csrf_token,
            "current_password": "Aa1!aaaaaa",
            "new_password": "Bb2@bbbbbb",
            "confirm_password": "Bb2@bbbbbb",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body.get("success") is True
    assert isinstance(body.get("csrf_token"), str) and len(body["csrf_token"]) == 64


# ──────────────────────────────────────────────────────────────────────
# /auth/2fa_challenge: redirect-without-import regression (M-NEW-6)
# ──────────────────────────────────────────────────────────────────────

def test_oauth_2fa_challenge_without_pending_session_redirects(client):
    """GET with no pending_2fa_user_id used to NameError on `redirect`
    (not imported). Must now 302 to home with oauth_error param."""
    r = client.get("/auth/2fa_challenge", follow_redirects=False)
    assert r.status_code == 302
    assert "/?oauth_error=no_pending_2fa" in r.headers["Location"]


def test_oauth_2fa_challenge_with_pending_session_renders_form(client, csrf_token):
    """Sanity: when pending_2fa_user_id is present, the inline form ships."""
    with client.session_transaction() as sess:
        sess["pending_2fa_user_id"] = 1
        sess["_csrf_token"] = csrf_token
    r = client.get("/auth/2fa_challenge")
    assert r.status_code == 200
    assert b"Two-factor code required" in r.data
    assert csrf_token.encode() in r.data  # server templates the token in


# ──────────────────────────────────────────────────────────────────────
# OAuth account-enumeration: non-verifying provider must not confirm that
# a password account exists for the email.
# ──────────────────────────────────────────────────────────────────────

def test_oauth_existing_password_account_returns_generic_error(client, app, monkeypatch):
    """A non-verifying provider signing in onto an existing password account
    must redirect with a GENERIC oauth_error, never a code that confirms the
    account exists (account-enumeration leak)."""
    import oauth as oauth_mod
    from database import db
    from models import User

    email = f"enum-{secrets.token_hex(3)}@example.com"
    with app.app_context():
        db.session.add(User(
            email=email,
            password_hash="$2b$12$" + "x" * 53,  # real bcrypt-shaped hash, not !OAUTH-
            api_tier="free",
            email_alerts_enabled=True,
            registration_date=datetime.utcnow(),
        ))
        db.session.commit()

    class _FakeClient:
        def authorize_access_token(self):
            return {"access_token": "t"}

    monkeypatch.setattr(oauth_mod, "_provider_enabled", lambda name: True)
    monkeypatch.setattr(oauth_mod.oauth, "create_client", lambda name: _FakeClient())
    monkeypatch.setattr(oauth_mod, "_resolve_email", lambda *a, **k: email)
    monkeypatch.setattr(oauth_mod, "_resolve_facebook_id", lambda *a, **k: "fb_enum_1")
    monkeypatch.setattr(oauth_mod, "_VERIFIED_EMAIL_PROVIDERS", {"google", "github"})

    r = client.get("/auth/facebook/callback", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert "password_account_exists" not in loc
    assert "oauth_error=provider_error" in loc


def test_oauth_verified_provider_links_to_existing_password_account(client, app, monkeypatch):
    """A verified-email provider (Google) signing in onto an existing
    password account links and logs the user in -- no provider_error."""
    import oauth as oauth_mod
    from database import db
    from models import User

    email = f"link-{secrets.token_hex(3)}@example.com"
    with app.app_context():
        db.session.add(User(
            email=email,
            password_hash="$2b$12$" + "x" * 53,
            api_tier="free",
            email_alerts_enabled=True,
            registration_date=datetime.utcnow(),
        ))
        db.session.commit()

    class _FakeClient:
        def authorize_access_token(self):
            return {"access_token": "t"}

    monkeypatch.setattr(oauth_mod, "_provider_enabled", lambda name: True)
    monkeypatch.setattr(oauth_mod.oauth, "create_client", lambda name: _FakeClient())
    monkeypatch.setattr(oauth_mod, "_resolve_email", lambda *a, **k: email)

    r = client.get("/auth/google/callback", follow_redirects=False)
    assert r.status_code == 302
    assert "oauth_error" not in r.headers["Location"]


# ──────────────────────────────────────────────────────────────────────
# Request body cap (H-NEW-1, MAX_CONTENT_LENGTH)
# ──────────────────────────────────────────────────────────────────────

def test_oversized_post_body_rejected_413(client, csrf_token):
    """1 MiB cap. A 2 MiB JSON body must 413 before reaching the handler."""
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    payload = {"junk": "A" * (2 * 1024 * 1024)}
    r = client.post(
        "/submit_location",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 413


# ──────────────────────────────────────────────────────────────────────
# /submit_location bounds (PR #299) — and the NaN edge case from self-audit
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload", [
    {"max_distance": 0.05},     # below lower distance bound
    {"max_distance": 10.5},     # above upper distance bound
    {"max_distance": "abc"},    # non-numeric distance
    {"limit": 0},               # limit too low (no max_distance ⇒ limit path)
    {"limit": 11},              # limit too high
    {"limit": "abc"},           # non-numeric limit
])
def test_submit_location_out_of_bounds_400(client, csrf_token, payload):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    body = {"lat": 52.23, "lng": 21.0, **payload}
    r = client.post(
        "/submit_location",
        data=json.dumps(body),
        content_type="application/json",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 400, r.data


# ──────────────────────────────────────────────────────────────────────
# Account lockout extended endpoints (PR #299)
# ──────────────────────────────────────────────────────────────────────

def test_change_password_records_failed_attempts(authed_client, csrf_token, app):
    """5 wrong current_password attempts on /account/password must trip
    User.locked_until — not just /login."""
    from models import User

    for _ in range(5):
        authed_client.post(
            "/account/password",
            data={
                "_csrf_token": csrf_token,
                "current_password": "wrong-password",
                "new_password": "Bb2@bbbbbb",
                "confirm_password": "Bb2@bbbbbb",
            },
            headers={"X-CSRF-Token": csrf_token},
        )
    with app.app_context():
        user = User.query.first()
        assert user is not None
        assert user.failed_login_attempts >= 5
        assert user.locked_until is not None
        assert user.locked_until > datetime.utcnow()


def test_locked_user_cannot_change_password(authed_client, csrf_token, app):
    """Once locked, even a correct current_password must be refused with
    403 + locked=True."""
    from database import db
    from models import User
    with app.app_context():
        user = User.query.first()
        user.locked_until = datetime.utcnow() + timedelta(minutes=15)
        db.session.commit()

    r = authed_client.post(
        "/account/password",
        data={
            "_csrf_token": csrf_token,
            "current_password": "Aa1!aaaaaa",
            "new_password": "Bb2@bbbbbb",
            "confirm_password": "Bb2@bbbbbb",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 403
    body = r.get_json()
    assert body.get("locked") is True


def test_record_failed_password_attempt_with_none_user_is_noop(app):
    """Defensive: helper must not raise on user=None (called only after a
    401 short-circuit, but the guard is the contract)."""
    import auth_routes
    with app.app_context():
        # No exception, no DB write.
        auth_routes._record_failed_password_attempt(None, endpoint="test")


# ──────────────────────────────────────────────────────────────────────
# ApiKey cascade-delete (C-NEW-1, fixed in a7e441f)
# ──────────────────────────────────────────────────────────────────────

def test_delete_account_cascades_to_api_keys(authed_client, csrf_token, app):
    """Deleting a user must remove their ApiKey rows in the same txn —
    otherwise orphans authenticate then crash /api/v1/* with NoneType."""
    from models import User, ApiKey

    # Mint a named API key against the authed user.
    r = authed_client.post(
        "/account/keys",
        data=json.dumps({"name": "test-key"}),
        content_type="application/json",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 200, r.data

    with app.app_context():
        user = User.query.first()
        user_id = user.id
        assert ApiKey.query.filter_by(user_id=user_id).count() >= 1

    # Delete the account.
    r = authed_client.post(
        "/account/delete",
        data=json.dumps({"current_password": "Aa1!aaaaaa", "confirm_phrase": "DELETE"}),
        content_type="application/json",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 200, r.data

    with app.app_context():
        assert User.query.get(user_id) is None
        # The cascade — no orphan keys left behind.
        assert ApiKey.query.filter_by(user_id=user_id).count() == 0


# ──────────────────────────────────────────────────────────────────────
# M1 — session epoch: a credential change evicts other live sessions
# ──────────────────────────────────────────────────────────────────────

def test_session_evicted_after_token_version_bump(authed_client, app):
    """A live session carries session['sv'] == user.session_token_version.
    Bumping that column (as change_password/reset_password do) must evict
    any session minted before the bump — global sign-out on credential
    change despite stateless signed-cookie sessions."""
    from database import db
    from models import User

    assert authed_client.get("/account").status_code == 200

    with app.app_context():
        user = User.query.first()
        user.session_token_version = (user.session_token_version or 0) + 1
        db.session.commit()

    assert authed_client.get("/account").status_code == 401


def test_password_change_bumps_version_and_keeps_current_session(authed_client, csrf_token, app):
    """change_password increments session_token_version (evicting other
    sessions) yet re-stamps the CURRENT session, so the user stays logged in
    on the device they changed the password from."""
    from models import User

    with app.app_context():
        before = User.query.first().session_token_version or 0

    r = authed_client.post(
        "/account/password",
        data={
            "_csrf_token": csrf_token,
            "current_password": "Aa1!aaaaaa",
            "new_password": "Zz9#zzzzzz",
            "confirm_password": "Zz9#zzzzzz",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 200, r.data

    with app.app_context():
        after = User.query.first().session_token_version or 0
    assert after == before + 1

    assert authed_client.get("/account").status_code == 200
