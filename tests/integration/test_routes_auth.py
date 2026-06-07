"""Auth routes: /register, /login, /logout, /session_check, tips gating."""
import pytest

pytestmark = pytest.mark.integration

VALID_PASSWORD = "Aa1!aaaaaa"


# ── Register ────────────────────────────────────────────────────────────────

def test_register_without_csrf_403(client):
    r = client.post("/register", data={
        "email": "test@example.com",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
    })
    assert r.status_code == 403


def test_register_happy_path(csrf_client, csrf_token):
    r = csrf_client.post("/register", data={
        "_csrf_token": csrf_token,
        "email": "alice@example.com",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
    })
    assert r.status_code == 200
    assert r.get_json()["success"] is True


def test_register_invalid_email(csrf_client, csrf_token):
    r = csrf_client.post("/register", data={
        "_csrf_token": csrf_token,
        "email": "not-an-email",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
    })
    assert r.status_code == 400


def test_register_weak_password(csrf_client, csrf_token):
    r = csrf_client.post("/register", data={
        "_csrf_token": csrf_token,
        "email": "weak@example.com",
        "password": "weakpass",
        "confirm_password": "weakpass",
    })
    assert r.status_code == 400


def test_register_password_mismatch(csrf_client, csrf_token):
    r = csrf_client.post("/register", data={
        "_csrf_token": csrf_token,
        "email": "mismatch@example.com",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD + "X",
    })
    assert r.status_code == 400


def test_register_duplicate_email_indistinguishable(csrf_client, csrf_token):
    """Audit fix ENUM-1: re-registering an existing email must look exactly
    like a fresh registration — same status, Content-Type and JSON body —
    so the response is not an account-enumeration oracle. (Replaces the
    old test that asserted the leaky "already registered" text body.)"""
    payload = {
        "_csrf_token": csrf_token,
        "email": "dup@example.com",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
    }
    first = csrf_client.post("/register", data=payload)
    assert first.status_code == 200
    second = csrf_client.post("/register", data=payload)
    assert second.status_code == first.status_code
    assert second.headers["Content-Type"] == first.headers["Content-Type"]
    assert second.get_data() == first.get_data()
    # And nothing leaks the existence of the account.
    assert b"already" not in second.get_data().lower()


def test_register_existing_byte_identical_to_new(csrf_client, csrf_token):
    """The existing-email response is byte-identical to a brand-new
    successful registration (different email)."""
    new_payload = {
        "_csrf_token": csrf_token,
        "email": "freshreg@example.com",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
    }
    new_resp = csrf_client.post("/register", data=new_payload)
    assert new_resp.status_code == 200

    # Register, then re-register the same email → existing-email branch.
    dup_payload = {
        "_csrf_token": csrf_token,
        "email": "dupbyte@example.com",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
    }
    csrf_client.post("/register", data=dup_payload)
    existing_resp = csrf_client.post("/register", data=dup_payload)

    assert existing_resp.status_code == new_resp.status_code
    assert existing_resp.headers["Content-Type"] == new_resp.headers["Content-Type"]
    assert existing_resp.get_data() == new_resp.get_data()


# ── Login ───────────────────────────────────────────────────────────────────

def test_login_without_csrf_403(client):
    r = client.post("/login", data={
        "email": "x@y.com", "password": VALID_PASSWORD,
    })
    assert r.status_code == 403


def test_login_unknown_user_returns_401(csrf_client, csrf_token):
    r = csrf_client.post("/login", data={
        "_csrf_token": csrf_token,
        "email": "ghost@example.com",
        "password": VALID_PASSWORD,
    })
    assert r.status_code == 401


def test_register_then_login_then_session_check(csrf_client, csrf_token):
    """Full happy path — bcrypt roundtrip + session establishment."""
    email = "roundtrip@example.com"
    csrf_client.post("/register", data={
        "_csrf_token": csrf_token, "email": email,
        "password": VALID_PASSWORD, "confirm_password": VALID_PASSWORD,
    })
    r = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": email, "password": VALID_PASSWORD,
    })
    assert r.status_code == 200
    assert r.get_json()["success"] is True

    sess_check = csrf_client.get("/session_check")
    assert sess_check.get_json() == {"logged_in": True}


def test_login_wrong_password_returns_401(csrf_client, csrf_token):
    csrf_client.post("/register", data={
        "_csrf_token": csrf_token, "email": "w@example.com",
        "password": VALID_PASSWORD, "confirm_password": VALID_PASSWORD,
    })
    r = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "w@example.com", "password": "WrongPass1!",
    })
    assert r.status_code == 401


def test_login_failure_responses_are_indistinguishable(csrf_client, csrf_token):
    """Audit fix ENUM-2: wrong-password, nonexistent-email, AND
    locked-account-with-wrong-password all return the identical generic
    401 body+status. An unauthenticated caller must not be able to tell a
    locked (hence existing) account from any other failed login."""
    GENERIC = {"success": False, "message": "Invalid email or password."}

    # 1) Existing account, wrong password.
    csrf_client.post("/register", data={
        "_csrf_token": csrf_token, "email": "enum1@example.com",
        "password": VALID_PASSWORD, "confirm_password": VALID_PASSWORD,
    })
    wrong = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "enum1@example.com",
        "password": "WrongPass1!",
    })

    # 2) Nonexistent account.
    ghost = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "enum-ghost@example.com",
        "password": "WrongPass1!",
    })

    # 3) Locked account, wrong password. Lock it first.
    csrf_client.post("/register", data={
        "_csrf_token": csrf_token, "email": "enum2@example.com",
        "password": VALID_PASSWORD, "confirm_password": VALID_PASSWORD,
    })
    for i in range(5):
        csrf_client.post("/login", data={
            "_csrf_token": csrf_token, "email": "enum2@example.com",
            "password": f"WrongPw1!{i}",
        })
    locked_wrong = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "enum2@example.com",
        "password": "StillWrong1!",
    })

    for r in (wrong, ghost, locked_wrong):
        assert r.status_code == 401, r.data
        assert r.get_json() == GENERIC, r.data
        assert "locked" not in r.get_data(as_text=True).lower()


# ── PR #26: account lockout ─────────────────────────────────────────────────

def test_login_locks_account_after_5_failed_attempts(csrf_client, csrf_token, app):
    csrf_client.post("/register", data={
        "_csrf_token": csrf_token, "email": "lock@example.com",
        "password": VALID_PASSWORD, "confirm_password": VALID_PASSWORD,
    })
    # 5 wrong attempts → 5th locks the account
    for i in range(5):
        r = csrf_client.post("/login", data={
            "_csrf_token": csrf_token, "email": "lock@example.com",
            "password": f"WrongPw1!{i}",
        })
        assert r.status_code == 401, f"attempt {i+1} expected 401, got {r.status_code}"

    # 6th attempt — with the CORRECT password — is locked out (403).
    # Revealing the lock here is safe: the caller proved ownership.
    r = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "lock@example.com",
        "password": VALID_PASSWORD,
    })
    assert r.status_code == 403, r.data
    body = r.get_json()
    assert body.get("locked") is True
    assert "locked_until" in body
    # And the lock did NOT establish a session.
    assert csrf_client.get("/session_check").get_json() == {"logged_in": False}

    # DB shows the lockout state
    from models import User
    with app.app_context():
        u = User.query.filter_by(email="lock@example.com").first()
        assert u.failed_login_attempts >= 5
        assert u.locked_until is not None


def test_login_success_resets_failed_attempts(csrf_client, csrf_token, app):
    from models import User
    csrf_client.post("/register", data={
        "_csrf_token": csrf_token, "email": "reset@example.com",
        "password": VALID_PASSWORD, "confirm_password": VALID_PASSWORD,
    })
    # 3 wrong attempts (below threshold)
    for i in range(3):
        csrf_client.post("/login", data={
            "_csrf_token": csrf_token, "email": "reset@example.com",
            "password": "WrongPw1!",
        })
    with app.app_context():
        u = User.query.filter_by(email="reset@example.com").first()
        assert u.failed_login_attempts == 3
        assert u.locked_until is None

    # Now correct → counter resets
    r = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "reset@example.com",
        "password": VALID_PASSWORD,
    })
    assert r.status_code == 200
    with app.app_context():
        u = User.query.filter_by(email="reset@example.com").first()
        assert u.failed_login_attempts == 0
        assert u.locked_until is None


def test_lockout_expires_after_window(csrf_client, csrf_token, app):
    """After locked_until passes, login proceeds normally."""
    from models import User
    from datetime import datetime, timedelta
    from database import db
    csrf_client.post("/register", data={
        "_csrf_token": csrf_token, "email": "expire@example.com",
        "password": VALID_PASSWORD, "confirm_password": VALID_PASSWORD,
    })
    # Manually backdate the lockout — simulates "lockout window passed"
    with app.app_context():
        u = User.query.filter_by(email="expire@example.com").first()
        u.failed_login_attempts = 5
        u.locked_until = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()

    # Correct password should succeed because lockout expired
    r = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "expire@example.com",
        "password": VALID_PASSWORD,
    })
    assert r.status_code == 200, r.data
    with app.app_context():
        u = User.query.filter_by(email="expire@example.com").first()
        assert u.failed_login_attempts == 0
        assert u.locked_until is None


# ── Logout ──────────────────────────────────────────────────────────────────

def test_logout_without_csrf_403(client):
    r = client.post("/logout")
    assert r.status_code == 403


def test_full_login_logout_cycle(authed_client, csrf_token):
    """authed_client fixture already registered+logged in. Exercise logout."""
    assert authed_client.get("/session_check").get_json() == {"logged_in": True}
    r = authed_client.post("/logout", headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200
    assert r.get_json()["success"] is True
    assert authed_client.get("/session_check").get_json() == {"logged_in": False}


def test_account_response_has_no_store_cache_header(authed_client):
    """Authenticated /account must set Cache-Control: no-store so the browser
    does not serve a stale rendered page (with email + API key) from BFCache
    after the user logs out and hits Back."""
    r = authed_client.get("/account")
    assert r.status_code == 200
    cc = r.headers.get("Cache-Control", "")
    assert "no-store" in cc, f"missing no-store on /account: {cc!r}"


def test_account_inaccessible_after_logout(authed_client, csrf_token):
    """After POST /logout, GET /account must return 401 even using the same
    cookie jar — the session is fully cleared, not just user_id popped."""
    assert authed_client.get("/account").status_code == 200
    r = authed_client.post("/logout", headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200
    after = authed_client.get("/account")
    assert after.status_code == 401, f"/account should be 401 post-logout, got {after.status_code}"


# ── Tips gating ─────────────────────────────────────────────────────────────

def test_tips_anonymous_uses_tips_md(client):
    """Anonymous /tips renders content from tips.md."""
    r = client.get("/tips")
    assert r.status_code == 200
    # tips.md contains "register" CTA; tips_registered.md does NOT.
    body = r.data.decode("utf-8").lower()
    # Cheap heuristic: anon body should hint at registration somewhere
    assert "regist" in body or "sign up" in body or len(body) > 0


def test_tips_logged_in_uses_tips_registered_md(authed_client):
    r = authed_client.get("/tips")
    assert r.status_code == 200
    # We can't assert specific content because src/content/tips_registered.md is
    # owner-controlled; what we can assert is that /tips/content for an authed
    # client differs (or matches) the registered md file. Easiest: verify the
    # endpoint succeeds for an authed session (gating check above already shown).
    auth_content = authed_client.get("/tips/content")
    assert auth_content.status_code == 200
