"""Email verification: token round-trip, resend, coverage-alert gating."""
import json

import pytest

pytestmark = pytest.mark.integration

VALID_PASSWORD = "Aa1!aaaaaa"
EMAIL = "verifyme@example.com"
WAW_LAT, WAW_LNG = 52.2297, 21.0122


def _register(csrf_client, csrf_token, email=EMAIL):
    r = csrf_client.post("/register", data={
        "_csrf_token": csrf_token,
        "email": email,
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
    })
    assert r.status_code == 200
    return r


def _verified_state(app, email=EMAIL):
    """(email_verified, email_verified_at) as plain values, session closed."""
    from database import db
    from models import User
    with app.app_context():
        u = User.query.filter_by(email=email).first()
        out = (u.email_verified, u.email_verified_at) if u else None
        db.session.remove()
    return out


def _make_token(app, email=EMAIL):
    from auth_routes import _make_email_verify_token
    from database import db
    from models import User
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        token = _make_email_verify_token(user)
        db.session.remove()
    return token


def test_new_signup_starts_unverified(app, csrf_client, csrf_token):
    _register(csrf_client, csrf_token)
    verified, at = _verified_state(app)
    assert verified is False
    assert at is None


def test_verify_email_happy_path(app, csrf_client, csrf_token):
    _register(csrf_client, csrf_token)
    token = _make_token(app)
    r = csrf_client.get(f"/verify-email?token={token}")
    assert r.status_code == 200
    assert b"Email verified" in r.data
    verified, _ = _verified_state(app)
    assert verified is True


def test_verify_email_idempotent(app, csrf_client, csrf_token):
    _register(csrf_client, csrf_token)
    token = _make_token(app)
    assert csrf_client.get(f"/verify-email?token={token}").status_code == 200
    _, first = _verified_state(app)
    assert csrf_client.get(f"/verify-email?token={token}").status_code == 200
    _, second = _verified_state(app)
    assert second == first


def test_verify_email_bad_token(client):
    assert client.get("/verify-email?token=garbage").status_code == 400
    assert client.get("/verify-email").status_code == 400


def test_token_bound_to_email(app, csrf_client, csrf_token):
    _register(csrf_client, csrf_token)
    token = _make_token(app)
    from database import db
    from models import User
    with app.app_context():
        user = User.query.filter_by(email=EMAIL).first()
        user.email = "changed@example.com"
        db.session.commit()
        db.session.remove()
    r = csrf_client.get(f"/verify-email?token={token}")
    assert r.status_code == 400
    verified, _ = _verified_state(app, "changed@example.com")
    assert verified is False


def test_resend_requires_login(csrf_client, csrf_token):
    r = csrf_client.post("/account/resend_verification",
                         data={"_csrf_token": csrf_token})
    assert r.status_code == 401


def test_resend_when_logged_in(app, csrf_client, csrf_token):
    _register(csrf_client, csrf_token)
    r = csrf_client.post("/login", data={
        "_csrf_token": csrf_token,
        "email": EMAIL,
        "password": VALID_PASSWORD,
    })
    assert r.status_code == 200
    # login rotates the session → re-plant the CSRF token
    with csrf_client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = csrf_client.post("/account/resend_verification",
                         data={"_csrf_token": csrf_token})
    assert r.status_code == 200
    assert r.get_json()["success"] is True


def test_coverage_alert_skips_unverified(app, csrf_client, csrf_token):
    _register(csrf_client, csrf_token)
    from coverage_alerts import _process
    from database import db
    from models import User, UserLocation
    with app.app_context():
        user = User.query.filter_by(email=EMAIL).first()
        loc = UserLocation(user_id=user.id, name="home",
                           lat=WAW_LAT, lng=WAW_LNG,
                           alerting_enabled=True,
                           last_coverage_state=json.dumps({}))
        db.session.add(loc)
        db.session.commit()
        status = _process(loc, dry_run=False, verbose=False)
        db.session.remove()
    assert status == 'skipped'


def test_account_page_shows_banner_until_verified(app, csrf_client, csrf_token):
    _register(csrf_client, csrf_token)
    csrf_client.post("/login", data={
        "_csrf_token": csrf_token,
        "email": EMAIL,
        "password": VALID_PASSWORD,
    })
    r = csrf_client.get("/account")
    assert b"resendVerification" in r.data
    token = _make_token(app)
    csrf_client.get(f"/verify-email?token={token}")
    r = csrf_client.get("/account")
    assert b"resendVerification" not in r.data
