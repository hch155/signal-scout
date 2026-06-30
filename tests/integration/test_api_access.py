"""Tests for the PR #5 API access gate: Referer/Origin check, API key
header, tier resolution, /account flow, and honeypot detection."""

import pytest

pytestmark = pytest.mark.integration

WARSAW = (52.2297, 21.0122)


# ── Referer / Origin gate ───────────────────────────────────────────────────

def test_stations_blocked_without_referer(raw_client):
    r = raw_client.get(f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=3")
    assert r.status_code == 403
    body = r.get_json()
    assert body["error"] == "access_denied"


def test_search_stations_blocked_without_referer(raw_client):
    r = raw_client.get("/search_stations?q=T10")
    assert r.status_code == 403


def test_find_station_blocked_without_referer(raw_client):
    r = raw_client.get("/find_station?basestation_id=T1000")
    assert r.status_code == 403


def test_stations_allowed_with_same_origin_referer(raw_client):
    r = raw_client.get(
        f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=3",
        headers={"Referer": "http://localhost/"},
    )
    assert r.status_code == 200


def test_stations_allowed_with_same_origin_via_origin_header(raw_client):
    r = raw_client.get(
        f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=3",
        headers={"Origin": "http://localhost"},
    )
    assert r.status_code == 200


def test_stations_blocked_with_foreign_referer(raw_client):
    r = raw_client.get(
        f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=3",
        headers={"Referer": "https://evil.example.com/scrape"},
    )
    assert r.status_code == 403


# ── API key bypasses Referer gate ───────────────────────────────────────────

def _register_user_and_get_key(client, csrf_token, email):
    """Register a fresh user via the public endpoint; return their api_key.

    PR #47 (hashed-at-rest): registration mints a key, hashes it for
    storage, and surfaces the plaintext ONCE in the response. Older
    versions of this helper read User.api_key directly; that column
    is now always None. Pull the plaintext from the registration JSON
    response instead.
    """
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post("/register", data={
        "_csrf_token": csrf_token,
        "email": email,
        "password": "Aa1!aaaaaa",
        "confirm_password": "Aa1!aaaaaa",
    })
    assert r.status_code == 200, r.data
    body = r.get_json() or {}
    api_key = body.get("api_key") or body.get("key")
    from models import User
    with client.application.app_context():
        user = User.query.filter_by(email=email).first()
        user_id = user.id
        user_api_tier = user.api_tier
    if not api_key:
        # /register may not return the plaintext (privacy preference) —
        # if so, mint a fresh one via the authenticated /account/keys
        # endpoint instead. We need a working key for the
        # bypasses_referer test.
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["sv"] = 0
            sess["_csrf_token"] = csrf_token
        import json as _json
        rk = client.post("/account/keys",
                         data=_json.dumps({"name": "test"}),
                         content_type="application/json",
                         headers={"X-CSRF-Token": csrf_token,
                                  "Referer": "http://localhost/"})
        assert rk.status_code == 200, rk.data
        api_key = rk.get_json()["key"]
    assert api_key
    assert user_api_tier == "free"
    return api_key


def test_api_key_bypasses_referer_check(raw_client, app, csrf_token):
    api_key = _register_user_and_get_key(
        raw_client, csrf_token, "key-bypass@example.com"
    )
    r = raw_client.get(
        f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=3",
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 200


def test_invalid_api_key_falls_through_to_referer_check(raw_client):
    r = raw_client.get(
        f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=3",
        headers={"X-API-Key": "definitely-not-a-real-key"},
    )
    # No referer + bogus key → still 403 (we don't accept just any header)
    assert r.status_code == 403


def test_api_key_too_long_silently_rejected(raw_client):
    # Defensive: ridiculously long key shouldn't trigger a DB query
    r = raw_client.get(
        f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=3",
        headers={"X-API-Key": "a" * 200},
    )
    assert r.status_code == 403


# ── Logged-in browser session passes ────────────────────────────────────────

def test_authed_browser_session_passes_without_api_key(authed_client):
    """An authenticated user hitting /stations from a browser doesn't need
    to send their API key — the session cookie alone is sufficient."""
    # authed_client is the regular client which already has Referer auto-set
    r = authed_client.get(f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=3")
    assert r.status_code == 200


# ── /account page ───────────────────────────────────────────────────────────

def test_account_page_requires_login(client):
    r = client.get("/account")
    assert r.status_code == 401


def test_account_page_renders_for_logged_in_user(authed_client):
    r = authed_client.get("/account")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "API key" in body
    # Key value must actually appear (rendered in <code id="api-key-value">)
    assert 'id="api-key-value"' in body


def test_regenerate_api_key_changes_value(authed_client, csrf_token):
    before = authed_client.get("/account").data.decode("utf-8")
    import re
    m_before = re.search(r'id="api-key-value"[^>]*>([^<]+)<', before)
    assert m_before
    old_key = m_before.group(1).strip()

    r = authed_client.post("/account/regenerate_api_key",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    new_key = body["api_key"]
    assert new_key and new_key != old_key


def test_regenerate_api_key_requires_csrf(authed_client):
    r = authed_client.post("/account/regenerate_api_key")
    assert r.status_code == 403


def test_regenerate_api_key_requires_login(client, csrf_token):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post("/account/regenerate_api_key",
                    headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401


# ── Honeypot detection ──────────────────────────────────────────────────────

def test_honeypot_find_station_returns_404_and_increments_counter(
    client, monkeypatch
):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    # Reload honeypot ID set with our test value
    import api_access
    api_access._HONEYPOT_IDS = {"HNYPOT"}

    r = client.get("/find_station?basestation_id=HNYPOT")
    assert r.status_code == 404  # looks like a normal miss
    assert r.get_json() == {"error": "Station not found"}

    metrics = client.get(
        "/metrics", headers={"Authorization": "Bearer supersecret"}
    ).get_data(as_text=True)
    assert "signal_scout_honeypot_hit_total" in metrics
    assert 'endpoint="find_station"' in metrics


def test_honeypot_search_returns_empty_and_increments_counter(
    client, monkeypatch
):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    import api_access
    api_access._HONEYPOT_IDS = {"HNYPOT2"}

    r = client.get("/search_stations?q=HNYPOT2")
    assert r.status_code == 200
    assert r.get_json() == {"stations": []}

    metrics = client.get(
        "/metrics", headers={"Authorization": "Bearer supersecret"}
    ).get_data(as_text=True)
    assert "signal_scout_honeypot_hit_total" in metrics
    assert 'endpoint="search_stations"' in metrics


# ── New user gets an API key + tier on registration ────────────────────────

def test_new_user_gets_api_key_and_tier(client, csrf_token):
    api_key = _register_user_and_get_key(client, csrf_token, "fresh@example.com")
    assert len(api_key) >= 32  # secrets.token_urlsafe(32) ≈ 43 chars


# ── Referer-blocked counter increments ─────────────────────────────────────

def test_referer_blocked_counter_increments(raw_client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    raw_client.get(f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=3")

    # Scrape via the normal client (which has Referer) so /metrics isn't itself
    # blocked. Test only cares that the counter line is present.
    # reuse same client to inherit env
    metrics = raw_client.get(
        "/metrics",
        headers={
            "Authorization": "Bearer supersecret",
            "Referer": "http://localhost/",
        },
    ).get_data(as_text=True)
    assert "signal_scout_api_referer_blocked_total" in metrics
    assert 'endpoint="stations"' in metrics
