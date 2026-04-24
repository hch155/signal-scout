"""PR #12: /account profile, change-password, delete routes.

The `authed_client` fixture registers a user with password 'Aa1!aaaaaa'
and logs them in. We use that known password for change-password / delete
flows here.
"""

import json

import pytest

from models import User


KNOWN_PW = "Aa1!aaaaaa"
NEW_PW = "Bb2@bbbbbb"


# ── Profile ────────────────────────────────────────────────────────────────

def test_profile_update_no_csrf_403(authed_client):
    r = authed_client.post("/account/profile",
                           data=json.dumps({"company": "Acme"}),
                           content_type="application/json")
    assert r.status_code == 403


def test_profile_company_field_persists(authed_client, csrf_token, app):
    """PR #19: simplified profile UI posts only `company`. Verify it lands."""
    r = authed_client.post("/account/profile",
                           data=json.dumps({"company": "Acme Corp."}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200, r.data
    with app.app_context():
        u = User.query.first()
        assert u.company == "Acme Corp."


def test_profile_company_only_update_lands(authed_client, csrf_token, app):
    """PR #36: legacy free-text profile columns are gone — `company` is
    the only writable field. Two consecutive POSTs of just `company`
    must overwrite the prior value cleanly."""
    authed_client.post("/account/profile",
                       data=json.dumps({"company": "Old Co."}),
                       content_type="application/json",
                       headers={"X-CSRF-Token": csrf_token})
    authed_client.post("/account/profile",
                       data=json.dumps({"company": "Acme"}),
                       content_type="application/json",
                       headers={"X-CSRF-Token": csrf_token})
    with app.app_context():
        u = User.query.first()
        assert u.company == "Acme"


def test_profile_company_too_long_rejected(authed_client, csrf_token):
    r = authed_client.post("/account/profile",
                           data=json.dumps({"company": "x" * 121}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 400


def test_profile_anon_returns_401(client, csrf_token):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post("/account/profile",
                    data=json.dumps({"company": "Mallory Inc."}),
                    content_type="application/json",
                    headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401


# ── Change password ────────────────────────────────────────────────────────

def test_change_password_no_csrf_403(authed_client):
    r = authed_client.post("/account/password",
                           data=json.dumps({"current_password": KNOWN_PW,
                                            "new_password": NEW_PW,
                                            "confirm_password": NEW_PW}),
                           content_type="application/json")
    assert r.status_code == 403


def test_change_password_wrong_current_rejected(authed_client, csrf_token):
    r = authed_client.post("/account/password",
                           data=json.dumps({"current_password": "WRONG-PW1!",
                                            "new_password": NEW_PW,
                                            "confirm_password": NEW_PW}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401


def test_change_password_weak_new_rejected(authed_client, csrf_token):
    r = authed_client.post("/account/password",
                           data=json.dumps({"current_password": KNOWN_PW,
                                            "new_password": "weakpw",
                                            "confirm_password": "weakpw"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 400


def test_change_password_mismatch_rejected(authed_client, csrf_token):
    r = authed_client.post("/account/password",
                           data=json.dumps({"current_password": KNOWN_PW,
                                            "new_password": NEW_PW,
                                            "confirm_password": "Cc3#cccccc"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 400


def test_change_password_same_as_old_rejected(authed_client, csrf_token):
    r = authed_client.post("/account/password",
                           data=json.dumps({"current_password": KNOWN_PW,
                                            "new_password": KNOWN_PW,
                                            "confirm_password": KNOWN_PW}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 400


def test_change_password_happy_path_can_login_with_new(authed_client, csrf_token, app, client):
    r = authed_client.post("/account/password",
                           data=json.dumps({"current_password": KNOWN_PW,
                                            "new_password": NEW_PW,
                                            "confirm_password": NEW_PW}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body["success"] is True
    assert "csrf_token" in body  # rotated token returned

    # Old-password login on a fresh client should now fail
    with app.app_context():
        email = User.query.first().email
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    bad = client.post("/login",
                      data={"_csrf_token": csrf_token, "email": email, "password": KNOWN_PW})
    assert bad.status_code == 401
    # New-password login works
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    good = client.post("/login",
                       data={"_csrf_token": csrf_token, "email": email, "password": NEW_PW})
    assert good.status_code == 200


# ── Delete account ─────────────────────────────────────────────────────────

def test_delete_no_csrf_403(authed_client):
    r = authed_client.post("/account/delete",
                           data=json.dumps({"current_password": KNOWN_PW,
                                            "confirm_phrase": "DELETE"}),
                           content_type="application/json")
    assert r.status_code == 403


def test_delete_wrong_password_rejected(authed_client, csrf_token, app):
    r = authed_client.post("/account/delete",
                           data=json.dumps({"current_password": "WRONG-PW1!",
                                            "confirm_phrase": "DELETE"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401
    with app.app_context():
        assert User.query.count() == 1  # not deleted


def test_delete_wrong_confirm_phrase_rejected(authed_client, csrf_token, app):
    # Stay within the /account/delete 3-per-hour rate limit. Three samples
    # cover the three bug classes: wrong-case, truncation, empty.
    for bad in ["delete", "DELET", ""]:
        r = authed_client.post("/account/delete",
                               data=json.dumps({"current_password": KNOWN_PW,
                                                "confirm_phrase": bad}),
                               content_type="application/json",
                               headers={"X-CSRF-Token": csrf_token})
        assert r.status_code == 400, f"expected 400 for phrase={bad!r}, got {r.status_code}"
    with app.app_context():
        assert User.query.count() == 1


def test_delete_happy_path_clears_session_and_row(authed_client, csrf_token, app):
    r = authed_client.post("/account/delete",
                           data=json.dumps({"current_password": KNOWN_PW,
                                            "confirm_phrase": "DELETE"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200, r.data
    assert r.get_json()["success"] is True

    with app.app_context():
        assert User.query.count() == 0

    after = authed_client.get("/account")
    assert after.status_code == 401


# ── Routes are inaccessible to anonymous users ─────────────────────────────

@pytest.mark.parametrize("path", ["/account/profile", "/account/password", "/account/delete"])
def test_anon_post_returns_401(client, csrf_token, path):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post(path,
                    data=json.dumps({"current_password": "x"}),
                    content_type="application/json",
                    headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401
