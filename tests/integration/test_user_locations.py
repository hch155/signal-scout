"""PR #30: multiple named user locations + per-location snapshots.

Covers CRUD happy paths, CSRF gates, PL bounds validation, auth gates,
cascade-on-delete (snapshots wiped when location removed), the
20-locations-per-user cap, and the alerting_enabled default.
"""

from __future__ import annotations

import json

import pytest

from models import User, UserLocation, UserStationSnapshot


# Centre of Warsaw — comfortably inside PL bounds, lots of dummy stations
# in the test fixture nearby so snapshot tests aren't empty.
WAW_LAT = 52.2297
WAW_LNG = 21.0122


def _create_payload(**overrides):
    base = {
        "name": "Home",
        "description": "primary residence",
        "lat": WAW_LAT,
        "lng": WAW_LNG,
        "radius_km": 10.0,
        "alerting_enabled": True,
    }
    base.update(overrides)
    return base


def _post_json(client, url, body, csrf_token):
    return client.post(
        url,
        data=json.dumps(body),
        content_type="application/json",
        headers={"X-CSRF-Token": csrf_token},
    )


# ── Auth + CSRF gates ─────────────────────────────────────────────────────

def test_create_location_anon_returns_401(client, csrf_token):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = _post_json(client, "/account/locations", _create_payload(), csrf_token)
    assert r.status_code == 401


def test_create_location_no_csrf_403(authed_client):
    r = authed_client.post(
        "/account/locations",
        data=json.dumps(_create_payload()),
        content_type="application/json",
    )
    assert r.status_code == 403


# ── Create happy path + alerting_enabled default ──────────────────────────

def test_create_location_happy_path(authed_client, csrf_token, app):
    r = _post_json(authed_client, "/account/locations",
                   _create_payload(), csrf_token)
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body["success"] is True
    loc = body["location"]
    assert loc["name"] == "Home"
    assert loc["description"] == "primary residence"
    assert loc["lat"] == pytest.approx(WAW_LAT, rel=1e-4)
    assert loc["lng"] == pytest.approx(WAW_LNG, rel=1e-4)
    assert loc["radius_km"] == pytest.approx(10.0)
    assert loc["alerting_enabled"] is True
    with app.app_context():
        row = UserLocation.query.get(loc["id"])
        assert row is not None
        assert row.alerting_enabled is True


def test_create_location_alerting_default_when_omitted(authed_client, csrf_token, app):
    payload = _create_payload()
    payload.pop("alerting_enabled")
    r = _post_json(authed_client, "/account/locations", payload, csrf_token)
    assert r.status_code == 200, r.data
    loc = r.get_json()["location"]
    # Default per the model = True (model column default + helper fallback).
    assert loc["alerting_enabled"] is True


# ── Validation: PL bounds, name, lat/lng pairing, radius ─────────────────

def test_create_location_outside_pl_bounds_400(authed_client, csrf_token):
    # Berlin — well outside PL bounds.
    r = _post_json(authed_client, "/account/locations",
                   _create_payload(lat=52.52, lng=13.40), csrf_token)
    assert r.status_code == 400
    assert "supported area" in r.get_json()["error"].lower()


def test_create_location_missing_name_400(authed_client, csrf_token):
    payload = _create_payload(name="")
    r = _post_json(authed_client, "/account/locations", payload, csrf_token)
    assert r.status_code == 400


def test_create_location_radius_out_of_range_400(authed_client, csrf_token):
    r = _post_json(authed_client, "/account/locations",
                   _create_payload(radius_km=999), csrf_token)
    assert r.status_code == 400


# ── List on /account ──────────────────────────────────────────────────────

def test_account_page_lists_saved_locations(authed_client, csrf_token):
    _post_json(authed_client, "/account/locations",
               _create_payload(name="Home"), csrf_token)
    _post_json(authed_client, "/account/locations",
               _create_payload(name="Office"), csrf_token)
    r = authed_client.get("/account")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Saved locations" in body
    assert "Home" in body
    assert "Office" in body


# ── Update ────────────────────────────────────────────────────────────────

def test_update_location_changes_fields(authed_client, csrf_token, app):
    create = _post_json(authed_client, "/account/locations",
                        _create_payload(), csrf_token)
    loc_id = create.get_json()["location"]["id"]

    r = _post_json(authed_client, f"/account/locations/{loc_id}",
                   {"name": "Renamed", "alerting_enabled": False,
                    "radius_km": 20}, csrf_token)
    assert r.status_code == 200, r.data
    out = r.get_json()["location"]
    assert out["name"] == "Renamed"
    assert out["alerting_enabled"] is False
    assert out["radius_km"] == pytest.approx(20.0)
    with app.app_context():
        row = UserLocation.query.get(loc_id)
        assert row.name == "Renamed"
        assert row.alerting_enabled is False


def test_update_other_users_location_404(client, csrf_token, authed_client, app):
    # Create a location owned by `authed_client` (the first user).
    create = _post_json(authed_client, "/account/locations",
                        _create_payload(), csrf_token)
    loc_id = create.get_json()["location"]["id"]

    # Now register + log in a *second* user via a fresh client.
    import secrets as _s
    email2 = f"user2-{_s.token_hex(4)}@example.com"
    pw = "Aa1!aaaaaa"
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    client.post("/register", data={"_csrf_token": csrf_token,
                                   "email": email2, "password": pw,
                                   "confirm_password": pw})
    client.post("/login", data={"_csrf_token": csrf_token,
                                "email": email2, "password": pw})
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token

    # Same response for not-found and not-owned, so we can't enumerate IDs.
    r = _post_json(client, f"/account/locations/{loc_id}",
                   {"name": "Hijacked"}, csrf_token)
    assert r.status_code == 404


# ── Delete + cascade ──────────────────────────────────────────────────────

def test_delete_location_removes_snapshots_cascade(authed_client, csrf_token, app):
    create = _post_json(authed_client, "/account/locations",
                        _create_payload(), csrf_token)
    loc_id = create.get_json()["location"]["id"]
    # Take a snapshot so there's something to cascade.
    snap_resp = authed_client.post(
        f"/account/locations/{loc_id}/snapshot",
        data="{}",
        content_type="application/json",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert snap_resp.status_code == 200, snap_resp.data
    snap_id = snap_resp.get_json()["snapshot_id"]

    with app.app_context():
        assert UserStationSnapshot.query.get(snap_id) is not None

    # Delete the location.
    r = authed_client.post(
        f"/account/locations/{loc_id}/delete",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 200, r.data

    with app.app_context():
        assert UserLocation.query.get(loc_id) is None
        # Cascade should have wiped the snapshot too.
        assert UserStationSnapshot.query.get(snap_id) is None


# ── Snapshot endpoint per location ────────────────────────────────────────

def test_take_location_snapshot_happy_path(authed_client, csrf_token, app):
    create = _post_json(authed_client, "/account/locations",
                        _create_payload(), csrf_token)
    loc_id = create.get_json()["location"]["id"]
    r = authed_client.post(
        f"/account/locations/{loc_id}/snapshot",
        data="{}",
        content_type="application/json",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body["success"] is True
    assert "snapshot_id" in body
    with app.app_context():
        snap = UserStationSnapshot.query.get(body["snapshot_id"])
        assert snap is not None
        assert snap.user_location_id == loc_id
        assert snap.centre_lat == pytest.approx(WAW_LAT, rel=1e-3)
        # stations_json must be valid JSON list (may be empty depending on fixture).
        stations = json.loads(snap.stations_json)
        assert isinstance(stations, list)


def test_take_snapshot_for_other_users_location_404(client, authed_client, csrf_token):
    create = _post_json(authed_client, "/account/locations",
                        _create_payload(), csrf_token)
    loc_id = create.get_json()["location"]["id"]

    import secrets as _s
    email2 = f"user2-{_s.token_hex(4)}@example.com"
    pw = "Aa1!aaaaaa"
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    client.post("/register", data={"_csrf_token": csrf_token,
                                   "email": email2, "password": pw,
                                   "confirm_password": pw})
    client.post("/login", data={"_csrf_token": csrf_token,
                                "email": email2, "password": pw})
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token

    r = client.post(
        f"/account/locations/{loc_id}/snapshot",
        data="{}",
        content_type="application/json",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 404


# ── Per-location changes page renders ─────────────────────────────────────

def test_location_changes_page_renders(authed_client, csrf_token):
    create = _post_json(authed_client, "/account/locations",
                        _create_payload(name="Cabin"), csrf_token)
    loc_id = create.get_json()["location"]["id"]
    r = authed_client.get(f"/account/locations/{loc_id}/changes")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Cabin" in body
    # No snapshots yet → empty-state copy.
    assert "No snapshots yet" in body


def test_location_changes_page_for_unknown_id_404(authed_client):
    r = authed_client.get("/account/locations/99999/changes")
    assert r.status_code == 404


# ── 20-per-user cap ───────────────────────────────────────────────────────

def test_create_location_caps_at_twenty(authed_client, csrf_token, app):
    # Bulk-insert 20 directly (faster than 20 POSTs which would also burn
    # the create rate-limit budget). Then attempt the 21st via the API.
    from database import db
    with app.app_context():
        u = User.query.first()
        for i in range(20):
            db.session.add(UserLocation(
                user_id=u.id, name=f"L{i}",
                lat=WAW_LAT, lng=WAW_LNG,
                radius_km=15.0, alerting_enabled=True,
            ))
        db.session.commit()

    r = _post_json(authed_client, "/account/locations",
                   _create_payload(name="Twenty-first"), csrf_token)
    assert r.status_code == 400
    assert "limit" in r.get_json()["error"].lower()
