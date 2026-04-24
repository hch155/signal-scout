"""PR #15: audit log + per-key API usage counters."""

import json

import pytest

from models import User, ApiKey, AuditEvent


KNOWN_PW = "Aa1!aaaaaa"
NEW_PW = "Bb2@bbbbbb"


def _events_for(app, *, event_type=None, user_id=None):
    with app.app_context():
        q = AuditEvent.query
        if user_id is not None:
            q = q.filter_by(user_id=user_id)
        if event_type is not None:
            q = q.filter_by(event_type=event_type)
        return q.order_by(AuditEvent.created_at.desc()).all()


# ── Hooks: each route writes the right event ──────────────────────────────

def test_login_success_writes_audit(authed_client, app):
    # authed_client fixture already registered + logged in
    events = _events_for(app, event_type='login.success')
    assert len(events) == 1, [e.event_type for e in _events_for(app)]
    assert events[0].user_agent is not None  # captured from request
    assert events[0].meta_json is None  # success has no meta


def test_login_fail_writes_audit_for_known_user(client, csrf_token, app):
    # Register a user via the public endpoint
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    client.post("/register", data={
        "_csrf_token": csrf_token,
        "email": "auditme@example.com",
        "password": KNOWN_PW,
        "confirm_password": KNOWN_PW,
    })
    # Wrong-password login
    client.post("/login", data={
        "_csrf_token": csrf_token,
        "email": "auditme@example.com",
        "password": "WRONG-PW1!",
    })
    fails = _events_for(app, event_type='login.fail')
    assert len(fails) == 1
    meta = json.loads(fails[0].meta_json)
    # PR #26 added an "attempts" counter to the meta payload; assert
    # subset rather than exact equality to keep the test forward-compatible.
    assert meta.get("reason") == "bad_password"
    assert isinstance(meta.get("attempts"), int)


def test_login_fail_for_unknown_email_does_not_audit(client, csrf_token, app):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post("/login", data={
        "_csrf_token": csrf_token,
        "email": "nobody-here@example.com",
        "password": "WhatEver1!",
    })
    assert r.status_code == 401
    # No User row, so no audit event written (no FK target).
    assert _events_for(app, event_type='login.fail') == []


def test_logout_writes_audit(authed_client, csrf_token, app):
    authed_client.post("/logout", headers={"X-CSRF-Token": csrf_token})
    logouts = _events_for(app, event_type='logout')
    assert len(logouts) == 1


def test_password_change_writes_audit(authed_client, csrf_token, app):
    authed_client.post("/account/password",
                       data=json.dumps({"current_password": KNOWN_PW,
                                        "new_password": NEW_PW,
                                        "confirm_password": NEW_PW}),
                       content_type="application/json",
                       headers={"X-CSRF-Token": csrf_token})
    pw = _events_for(app, event_type='password.changed')
    assert len(pw) == 1


def test_profile_update_writes_audit(authed_client, csrf_token, app):
    authed_client.post("/account/profile",
                       data=json.dumps({"company": "Audit Tester Co."}),
                       content_type="application/json",
                       headers={"X-CSRF-Token": csrf_token})
    pe = _events_for(app, event_type='profile.updated')
    assert len(pe) == 1


def test_apikey_create_revoke_audit(authed_client, csrf_token, app):
    c = authed_client.post("/account/keys",
                           data=json.dumps({"name": "audit-key"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    kid = c.get_json()["id"]
    authed_client.post(f"/account/keys/{kid}/revoke",
                       headers={"X-CSRF-Token": csrf_token})
    cre = _events_for(app, event_type='apikey.created')
    rev = _events_for(app, event_type='apikey.revoked')
    assert len(cre) == 1
    assert len(rev) == 1
    assert json.loads(cre[0].meta_json)["name"] == "audit-key"
    assert json.loads(rev[0].meta_json)["key_id"] == kid


# ── Account page renders activity ─────────────────────────────────────────

def test_account_page_renders_audit_events(authed_client, csrf_token):
    # The login-success event from the fixture should already be visible.
    r = authed_client.get("/account")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Recent activity" in body
    assert "login.success" in body


# ── Account delete cascades audit rows away (GDPR) ────────────────────────

def test_account_delete_cascades_audit(authed_client, csrf_token, app):
    # Generate some events first
    authed_client.post("/account/profile",
                       data=json.dumps({"company": "X"}),
                       content_type="application/json",
                       headers={"X-CSRF-Token": csrf_token})
    with app.app_context():
        before = AuditEvent.query.count()
    assert before >= 2  # at least login.success + profile.updated

    # Delete account
    authed_client.post("/account/delete",
                       data=json.dumps({"current_password": KNOWN_PW,
                                        "confirm_phrase": "DELETE"}),
                       content_type="application/json",
                       headers={"X-CSRF-Token": csrf_token})
    with app.app_context():
        # CASCADE wiped the user's audit history along with the user row
        assert AuditEvent.query.count() == 0
        assert User.query.count() == 0


# ── Per-key call counter ──────────────────────────────────────────────────

def test_apikey_total_calls_increments_on_authenticated_request(
    authed_client, csrf_token, raw_client, app
):
    # Create a key
    r = authed_client.post("/account/keys",
                           data=json.dumps({"name": "counter-test"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    body = r.get_json()
    new_key = body["key"]
    kid = body["id"]

    # Initial state
    with app.app_context():
        ak = ApiKey.query.get(kid)
        assert ak.total_calls == 0
        assert ak.last_used_at is None

    # Hit the API a few times
    for _ in range(3):
        rr = raw_client.get("/stations?lat=52.23&lng=21.01&limit=2",
                            headers={"X-API-Key": new_key})
        assert rr.status_code == 200

    with app.app_context():
        ak = ApiKey.query.get(kid)
        assert ak.total_calls == 3, f"expected 3, got {ak.total_calls}"
        assert ak.last_used_at is not None


def test_revoked_key_does_not_increment_counter(authed_client, csrf_token, raw_client, app):
    r = authed_client.post("/account/keys",
                           data=json.dumps({"name": "revoke-counter"}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    body = r.get_json()
    new_key = body["key"]
    kid = body["id"]

    # One successful call → counter = 1
    raw_client.get("/stations?lat=52.23&lng=21.01&limit=2",
                   headers={"X-API-Key": new_key})
    with app.app_context():
        assert ApiKey.query.get(kid).total_calls == 1

    # Revoke
    authed_client.post(f"/account/keys/{kid}/revoke",
                       headers={"X-CSRF-Token": csrf_token})

    # Try to use again — denied, no counter bump
    rr = raw_client.get("/stations?lat=52.23&lng=21.01&limit=2",
                        headers={"X-API-Key": new_key})
    assert rr.status_code == 403
    with app.app_context():
        assert ApiKey.query.get(kid).total_calls == 1  # unchanged
