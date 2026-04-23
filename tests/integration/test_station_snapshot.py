"""PR #29: per-user station snapshot + diff feed."""

import json

import pytest

from models import User, UserStationSnapshot


KNOWN_PW = "Aa1!aaaaaa"


def _set_user_location(app, lat=52.2297, lng=21.0122):
    from database import db
    with app.app_context():
        u = User.query.first()
        u.last_location_lat = lat
        u.last_location_lng = lng
        db.session.commit()


# ── Snapshot endpoint ──────────────────────────────────────────────────────

def test_snapshot_no_csrf_403(authed_client):
    r = authed_client.post("/account/snapshot")
    assert r.status_code == 403


def test_snapshot_anon_returns_401(client, csrf_token):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post("/account/snapshot",
                    headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 401


def test_snapshot_without_saved_location_400(authed_client, csrf_token, app):
    # Brand-new user has no last_location_* yet
    r = authed_client.post("/account/snapshot",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 400
    assert "saved location" in r.get_json()["error"].lower()


def test_snapshot_happy_path(authed_client, csrf_token, app):
    _set_user_location(app)
    r = authed_client.post("/account/snapshot",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body["success"] is True
    assert "snapshot_id" in body
    assert "count" in body
    with app.app_context():
        snap = UserStationSnapshot.query.get(body["snapshot_id"])
        assert snap is not None
        stations = json.loads(snap.stations_json)
        assert isinstance(stations, list)
        assert snap.centre_lat == pytest.approx(52.2297, rel=1e-3)


# ── Saved-location persisted via /submit_location for logged-in user ──────

def test_submit_location_persists_to_user_when_logged_in(authed_client, csrf_token, app):
    r = authed_client.post("/submit_location",
                           data=json.dumps({"lat": 52.2297, "lng": 21.0122, "limit": 3}),
                           content_type="application/json",
                           headers={"X-CSRF-Token": csrf_token})
    assert r.status_code == 200, r.data
    with app.app_context():
        u = User.query.first()
        assert u.last_location_lat == pytest.approx(52.2297, rel=1e-3)
        assert u.last_location_lng == pytest.approx(21.0122, rel=1e-3)


# ── /account/changes page ─────────────────────────────────────────────────

def test_changes_page_anon_401(client):
    r = client.get("/account/changes")
    assert r.status_code == 401


def test_changes_page_no_location_message(authed_client):
    r = authed_client.get("/account/changes")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "No saved location" in body


def test_changes_page_one_snapshot_no_diff(authed_client, csrf_token, app):
    _set_user_location(app)
    authed_client.post("/account/snapshot", headers={"X-CSRF-Token": csrf_token})
    r = authed_client.get("/account/changes")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "First snapshot" in body or "snapshot" in body.lower()


def test_changes_page_renders_diff_between_two_snapshots(authed_client, csrf_token, app):
    _set_user_location(app)
    # First snapshot
    authed_client.post("/account/snapshot", headers={"X-CSRF-Token": csrf_token})
    # Wait briefly so the second snapshot has a strictly later timestamp
    import time; time.sleep(0.01)
    # Second snapshot of the same data — diff should be empty (no changes)
    authed_client.post("/account/snapshot", headers={"X-CSRF-Token": csrf_token})
    r = authed_client.get("/account/changes")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    # Empty-diff branch:
    assert "No changes" in body or "0 added" in body or "0 removed" in body


# ── Diff helper unit ──────────────────────────────────────────────────────

def test_compute_snapshot_diff_added_removed_changed():
    from auth_routes import compute_snapshot_diff
    prev = [
        {"basestation_id": "WAR1", "frequency_bands": ["LTE800", "LTE1800"], "service_provider": "Orange"},
        {"basestation_id": "WAR2", "frequency_bands": ["LTE800"], "service_provider": "Plus"},
        {"basestation_id": "WAR3", "frequency_bands": ["GSM900"], "service_provider": "T-Mobile"},
    ]
    curr = [
        {"basestation_id": "WAR1", "frequency_bands": ["LTE800", "LTE1800", "5G2100"], "service_provider": "Orange"},
        # WAR2 removed
        {"basestation_id": "WAR3", "frequency_bands": ["GSM900"], "service_provider": "T-Mobile"},
        {"basestation_id": "WAR4", "frequency_bands": ["LTE2600"], "service_provider": "Play"},
    ]
    d = compute_snapshot_diff(prev, curr)
    added_ids = {s["basestation_id"] for s in d["added"]}
    removed_ids = {s["basestation_id"] for s in d["removed"]}
    band_ids = {c["station"]["basestation_id"] for c in d["band_changed"]}
    assert added_ids == {"WAR4"}
    assert removed_ids == {"WAR2"}
    assert band_ids == {"WAR1"}
    war1_change = next(c for c in d["band_changed"] if c["station"]["basestation_id"] == "WAR1")
    assert war1_change["added_bands"] == ["5G2100"]
    assert war1_change["removed_bands"] == []
