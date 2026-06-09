"""Password-reset (forgot-password) backend — 2026-06-08.

Covers: anti-enumeration parity on POST /forgot-password, token validity /
expiry / tampering on GET+POST /reset-password, single-use via pwf binding,
password policy enforcement, and a rate-limit smoke check.
"""
import pytest

pytestmark = pytest.mark.integration

VALID_PASSWORD = "Aa1!aaaaaa"
NEW_PASSWORD = "Bb2@bbbbbb"


def _register(csrf_client, csrf_token, email, password=VALID_PASSWORD):
    r = csrf_client.post("/register", data={
        "_csrf_token": csrf_token, "email": email,
        "password": password, "confirm_password": password,
    })
    assert r.status_code == 200, r.data


def _make_token(app, email):
    """Mint a real reset token for `email` the same way the route does."""
    import auth_routes
    from models import User
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        return auth_routes._make_password_reset_token(user)


# ── Anti-enumeration ────────────────────────────────────────────────────────

def test_forgot_password_without_csrf_403(client):
    r = client.post("/forgot-password", data={"email": "x@y.com"})
    assert r.status_code == 403


def test_forgot_password_existing_vs_nonexistent_byte_identical(csrf_client, csrf_token):
    _register(csrf_client, csrf_token, "exists@example.com")

    existing = csrf_client.post("/forgot-password", data={
        "_csrf_token": csrf_token, "email": "exists@example.com",
    })
    nonexistent = csrf_client.post("/forgot-password", data={
        "_csrf_token": csrf_token, "email": "nobody@example.com",
    })

    assert existing.status_code == 200
    assert nonexistent.status_code == existing.status_code
    assert nonexistent.headers["Content-Type"] == existing.headers["Content-Type"]
    assert nonexistent.get_data() == existing.get_data()
    assert b"sent a password reset link" in existing.get_data()


def test_forgot_password_oauth_only_user_identical(csrf_client, csrf_token, app):
    """A user with no local password (OAuth-only) yields the identical
    generic response and sends no usable reset."""
    from models import User
    from database import db
    with app.app_context():
        db.session.add(User(email="oauth@example.com", password_hash=None))
        db.session.commit()

    oauth = csrf_client.post("/forgot-password", data={
        "_csrf_token": csrf_token, "email": "oauth@example.com",
    })
    ghost = csrf_client.post("/forgot-password", data={
        "_csrf_token": csrf_token, "email": "ghost@example.com",
    })
    assert oauth.status_code == 200
    assert oauth.get_data() == ghost.get_data()


# ── Token validity / GET + POST reset ───────────────────────────────────────

def test_reset_password_get_valid_token(csrf_client, csrf_token, app):
    _register(csrf_client, csrf_token, "getvalid@example.com")
    token = _make_token(app, "getvalid@example.com")
    r = csrf_client.get(f"/reset-password?token={token}")
    assert r.status_code == 200
    assert b"invalid or has expired" not in r.get_data()


def test_reset_password_get_tampered_token(csrf_client, csrf_token, app):
    _register(csrf_client, csrf_token, "tamper@example.com")
    token = _make_token(app, "tamper@example.com")
    r = csrf_client.get(f"/reset-password?token={token}x« broken")
    assert r.status_code == 400
    assert b"invalid or has expired" in r.get_data()


def test_reset_password_get_missing_token(csrf_client):
    r = csrf_client.get("/reset-password")
    assert r.status_code == 400
    assert b"invalid or has expired" in r.get_data()


def test_reset_password_expired_token_rejected(csrf_client, csrf_token, app):
    """Simulate an expired token by signing with a tiny max_age on verify."""
    import auth_routes
    _register(csrf_client, csrf_token, "expired@example.com")
    token = _make_token(app, "expired@example.com")
    with app.app_context():
        orig = auth_routes._PW_RESET_MAX_AGE
        auth_routes._PW_RESET_MAX_AGE = -1  # everything is already "too old"
        try:
            user = auth_routes._verify_password_reset_token(token)
        finally:
            auth_routes._PW_RESET_MAX_AGE = orig
    assert user is None


def test_reset_password_post_success_changes_password(csrf_client, csrf_token, app):
    _register(csrf_client, csrf_token, "resetme@example.com")
    token = _make_token(app, "resetme@example.com")

    r = csrf_client.post("/reset-password", data={
        "_csrf_token": csrf_token, "token": token,
        "password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
    })
    assert r.status_code == 200
    assert b"now sign in" in r.get_data() or b"Password updated" in r.get_data()

    # New password works, old does not.
    login_new = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "resetme@example.com",
        "password": NEW_PASSWORD,
    })
    assert login_new.status_code == 200
    # Successful login rotates the session CSRF token — re-plant ours.
    with csrf_client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    login_old = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "resetme@example.com",
        "password": VALID_PASSWORD,
    })
    assert login_old.status_code == 401


# ── Single use (pwf binding) ────────────────────────────────────────────────

def test_old_token_rejected_after_reset(csrf_client, csrf_token, app):
    _register(csrf_client, csrf_token, "single@example.com")
    token = _make_token(app, "single@example.com")

    first = csrf_client.post("/reset-password", data={
        "_csrf_token": csrf_token, "token": token,
        "password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
    })
    assert first.status_code == 200

    # Re-presenting the same token: pwf no longer matches the new hash.
    reuse = csrf_client.post("/reset-password", data={
        "_csrf_token": csrf_token, "token": token,
        "password": "Cc3#cccccc", "confirm_password": "Cc3#cccccc",
    })
    assert reuse.status_code == 400
    assert b"invalid or has expired" in reuse.get_data()


# ── Password policy ─────────────────────────────────────────────────────────

def test_reset_password_weak_rejected(csrf_client, csrf_token, app):
    _register(csrf_client, csrf_token, "weakreset@example.com")
    token = _make_token(app, "weakreset@example.com")
    r = csrf_client.post("/reset-password", data={
        "_csrf_token": csrf_token, "token": token,
        "password": "weakpass", "confirm_password": "weakpass",
    })
    assert r.status_code == 400
    assert b"does not meet criteria" in r.get_data()
    # Old password still works — nothing changed.
    login_old = csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "weakreset@example.com",
        "password": VALID_PASSWORD,
    })
    assert login_old.status_code == 200


def test_reset_password_mismatch_rejected(csrf_client, csrf_token, app):
    _register(csrf_client, csrf_token, "mismatchreset@example.com")
    token = _make_token(app, "mismatchreset@example.com")
    r = csrf_client.post("/reset-password", data={
        "_csrf_token": csrf_token, "token": token,
        "password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD + "X",
    })
    assert r.status_code == 400
    assert b"do not match" in r.get_data()


def test_reset_clears_lockout(csrf_client, csrf_token, app):
    from models import User
    from database import db
    from datetime import datetime, timedelta
    _register(csrf_client, csrf_token, "lockedreset@example.com")
    with app.app_context():
        u = User.query.filter_by(email="lockedreset@example.com").first()
        u.failed_login_attempts = 5
        u.locked_until = datetime.utcnow() + timedelta(minutes=15)
        db.session.commit()
    token = _make_token(app, "lockedreset@example.com")
    r = csrf_client.post("/reset-password", data={
        "_csrf_token": csrf_token, "token": token,
        "password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
    })
    assert r.status_code == 200
    with app.app_context():
        u = User.query.filter_by(email="lockedreset@example.com").first()
        assert u.failed_login_attempts == 0
        assert u.locked_until is None


# ── Email sender + rate-limit smoke ─────────────────────────────────────────

def test_forgot_password_sends_email_for_existing_user(csrf_client, csrf_token, monkeypatch):
    import emails
    sent = []
    monkeypatch.setattr(emails, "send_password_reset",
                        lambda user, url: sent.append((user.email, url)) or True)
    _register(csrf_client, csrf_token, "mailed@example.com")
    csrf_client.post("/forgot-password", data={
        "_csrf_token": csrf_token, "email": "mailed@example.com",
    })
    assert len(sent) == 1
    assert sent[0][0] == "mailed@example.com"
    assert "/reset-password?token=" in sent[0][1]


def test_forgot_password_rate_limited(csrf_client, csrf_token):
    _register(csrf_client, csrf_token, "ratelimited@example.com")
    codes = []
    for _ in range(7):
        r = csrf_client.post("/forgot-password", data={
            "_csrf_token": csrf_token, "email": "ratelimited@example.com",
        })
        codes.append(r.status_code)
    # "5 per hour" → at least one 429 within 7 attempts on the same IP+email.
    assert 429 in codes
