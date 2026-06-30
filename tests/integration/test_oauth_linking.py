"""Secure Facebook account linking.

Facebook's Graph API exposes no email-verification signal, so Facebook must
never auto-link by email (that is the account-takeover vector closed in
oauth.py). Instead a Facebook identity is bound to a user explicitly, from
/account, behind a password step-up, and recorded as User.facebook_user_id.
Sign-in then matches by that id, never by email.
"""

import json
import secrets
from datetime import datetime


KNOWN_PW = "Aa1!aaaaaa"


class _FakeClient:
    def authorize_access_token(self):
        return {"access_token": "t"}


def _patch_fb(monkeypatch, fb_id, email=None):
    import oauth as oauth_mod
    monkeypatch.setattr(oauth_mod, "_provider_enabled", lambda n: True)
    monkeypatch.setattr(oauth_mod.oauth, "create_client", lambda n: _FakeClient())
    monkeypatch.setattr(oauth_mod, "_resolve_facebook_id", lambda *a, **k: fb_id)
    if email is not None:
        monkeypatch.setattr(oauth_mod, "_resolve_email", lambda *a, **k: email)


# ── Sign-in matches by linked id, never by email ──────────────────────────

def test_facebook_login_by_linked_id_logs_in(client, app, monkeypatch):
    from database import db
    from models import User
    email = f"fbid-{secrets.token_hex(3)}@example.com"
    with app.app_context():
        db.session.add(User(
            email=email, password_hash="$2b$12$" + "x" * 53, api_tier="free",
            email_alerts_enabled=True, registration_date=datetime.utcnow(),
            facebook_user_id="FBLINKED1"))
        db.session.commit()

    _patch_fb(monkeypatch, "FBLINKED1")
    r = client.get("/auth/facebook/callback", follow_redirects=False)
    assert r.status_code == 302
    assert "oauth_error" not in r.headers["Location"]
    assert client.get("/session_check").get_json() == {"logged_in": True}


def test_facebook_login_creates_account_when_email_unseen(client, app, monkeypatch):
    from models import User
    email = f"fbnew-{secrets.token_hex(3)}@example.com"
    _patch_fb(monkeypatch, "FBNEW1", email=email)

    r = client.get("/auth/facebook/callback", follow_redirects=False)
    assert r.status_code == 302
    assert "oauth_error" not in r.headers["Location"]
    with app.app_context():
        u = User.query.filter_by(facebook_user_id="FBNEW1").first()
        assert u is not None and u.email.lower() == email.lower()
        # Facebook's email is unverifiable → not stamped verified.
        assert u.email_verified_at is None


def test_facebook_login_refused_when_email_owned_by_other_account(client, app, monkeypatch):
    """The takeover case: an unlinked FB id whose email already belongs to a
    password account must be refused (the owner links it from /account)."""
    from database import db
    from models import User
    email = f"fbcollide-{secrets.token_hex(3)}@example.com"
    with app.app_context():
        db.session.add(User(
            email=email, password_hash="$2b$12$" + "x" * 53, api_tier="free",
            email_alerts_enabled=True, registration_date=datetime.utcnow()))
        db.session.commit()

    _patch_fb(monkeypatch, "FBOTHER1", email=email)
    r = client.get("/auth/facebook/callback", follow_redirects=False)
    assert r.status_code == 302
    assert "oauth_error=provider_error" in r.headers["Location"]
    assert client.get("/session_check").get_json() == {"logged_in": False}


# ── Explicit link / unlink from /account ──────────────────────────────────

def test_facebook_link_binds_id_to_logged_in_user(authed_client, app, monkeypatch):
    from models import User
    with app.app_context():
        uid = User.query.first().id

    _patch_fb(monkeypatch, "FBLINKME")
    # Simulate the intent that start_facebook_link plants after the step-up.
    with authed_client.session_transaction() as s:
        s["oauth_link_user_id"] = uid
        s["oauth_link_provider"] = "facebook"

    r = authed_client.get("/auth/facebook/callback", follow_redirects=False)
    assert r.status_code == 302
    assert "linked=facebook" in r.headers["Location"]
    with app.app_context():
        assert User.query.get(uid).facebook_user_id == "FBLINKME"


def test_start_link_requires_password_step_up(authed_client, csrf_token, monkeypatch):
    import oauth as oauth_mod
    monkeypatch.setattr(oauth_mod, "_provider_enabled", lambda n: True)

    # No password → 401
    r = authed_client.post("/account/link/facebook",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401
    # Wrong password → 401
    r = authed_client.post("/account/link/facebook",
                           data=json.dumps({"current_password": "WRONG-PW1!"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401

    # Correct password → 200 + an authorize_url to hand off to Facebook.
    class _FC:
        def authorize_redirect(self, uri):
            from flask import redirect as _r
            return _r("https://www.facebook.com/v18.0/dialog/oauth?state=x")
    monkeypatch.setattr(oauth_mod.oauth, "create_client", lambda n: _FC())
    r = authed_client.post("/account/link/facebook",
                           data=json.dumps({"current_password": KNOWN_PW}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200
    assert "facebook.com" in r.get_json()["authorize_url"]


def test_unlink_requires_password_and_keeps_signin(authed_client, csrf_token, app):
    from database import db
    from models import User
    with app.app_context():
        u = User.query.first()
        u.facebook_user_id = "FBTOUNLINK"
        db.session.commit()

    # Wrong password → 401, still linked
    r = authed_client.post("/account/unlink/facebook",
                           data=json.dumps({"current_password": "WRONG-PW1!"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401

    # Correct password → 200, unlinked
    r = authed_client.post("/account/unlink/facebook",
                           data=json.dumps({"current_password": KNOWN_PW}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200
    with app.app_context():
        assert User.query.first().facebook_user_id is None
