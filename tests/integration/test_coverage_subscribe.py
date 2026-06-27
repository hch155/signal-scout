"""Coverage-alert subscription by address.

Covers the POST /coverage/subscribe view (auth + CSRF gates, geocode +
upsert, validation/no-match mapping), the subscribe_address helper
(create / upsert / no-match / limit / outside-PL), and the real5g_delta
classifier the sweep uses to flag gained/lost "real 5G".

The view is exercised directly inside a test_request_context: the route
is registered from app.py in production (a returned integration point),
but Flask 3.x forbids registering a blueprint on the shared session app
after it has handled its first request, so we call the view function as
the unit it is.
"""
from __future__ import annotations

import pytest

from database import db
from models import User, UserLocation

pytestmark = pytest.mark.integration

CSRF = "test-csrf-token"

# Address present in the test fixture (tests/conftest.py): geocodes to
# Warsaw, which has dummy stations nearby so the coverage resolve succeeds.
KNOWN_QUERY = "Marszałkowska Warszawa"
KNOWN_DISPLAY = "Marszałkowska, Warszawa"
OTHER_QUERY = "Ogrodnicza Białystok"
NO_MATCH_QUERY = "Qwerty Zxcvbnm Nowhere"


def _make_user(app):
    user = User(email="sub@example.com", password_hash="x", role="user",
                email_alerts_enabled=True)
    db.session.add(user)
    db.session.commit()
    return user


def _call_view(app, query, *, user_id=None, csrf=True):
    """Invoke the coverage_subscribe view inside a request context and
    return (status_code, json_body)."""
    from flask import session
    from coverage_subscribe_routes import coverage_subscribe
    headers = {"X-CSRF-Token": CSRF} if csrf else {}
    with app.test_request_context("/coverage/subscribe", method="POST",
                                  json={"query": query}, headers=headers):
        session["_csrf_token"] = CSRF
        if user_id is not None:
            session["user_id"] = user_id
        resp, status = coverage_subscribe()
        return status, resp.get_json()


# ── View: auth + CSRF gates ──────────────────────────────────────────────

def test_subscribe_anon_returns_401(app):
    with app.app_context():
        status, _ = _call_view(app, KNOWN_QUERY, user_id=None)
        assert status == 401


def test_subscribe_no_csrf_returns_403(app):
    with app.app_context():
        user = _make_user(app)
        status, body = _call_view(app, KNOWN_QUERY, user_id=user.id, csrf=False)
        assert status == 403
        assert body["error"] == "Invalid request"


# ── View: happy path + upsert + validation ───────────────────────────────

def test_subscribe_happy_path_creates_alerting_location(app):
    with app.app_context():
        user = _make_user(app)
        status, body = _call_view(app, KNOWN_QUERY, user_id=user.id)
        assert status == 200, body
        assert body["success"] is True
        assert body["created"] is True
        assert body["location"]["name"] == KNOWN_DISPLAY
        assert body["location"]["alerting_enabled"] is True
        assert body["match"]["display"] == KNOWN_DISPLAY

        rows = UserLocation.query.filter_by(user_id=user.id).all()
        assert len(rows) == 1
        assert rows[0].alerting_enabled is True
        assert rows[0].radius_km == pytest.approx(0.0)
        assert rows[0].lat == pytest.approx(52.2297, abs=1e-3)


def test_subscribe_same_address_upserts_not_duplicates(app):
    with app.app_context():
        user = _make_user(app)
        first_status, first = _call_view(app, KNOWN_QUERY, user_id=user.id)
        assert first_status == 200
        assert first["created"] is True
        second_status, second = _call_view(app, KNOWN_QUERY, user_id=user.id)
        assert second_status == 200
        assert second["created"] is False
        assert UserLocation.query.filter_by(user_id=user.id).count() == 1


def test_subscribe_short_query_returns_invalid_input(app):
    with app.app_context():
        user = _make_user(app)
        status, body = _call_view(app, "ab", user_id=user.id)
        assert status == 400
        assert body["error"] == "invalid_input"


def test_subscribe_unknown_address_returns_404(app):
    with app.app_context():
        user = _make_user(app)
        status, body = _call_view(app, NO_MATCH_QUERY, user_id=user.id)
        assert status == 404
        assert body["error"] == "no_match"


# ── Helper: subscribe_address ────────────────────────────────────────────

def test_subscribe_address_creates_and_then_upserts(app):
    from coverage_subscribe import subscribe_address

    with app.app_context():
        user = _make_user(app)

        created = subscribe_address(user, KNOWN_QUERY)
        assert created["status"] == "ok"
        assert created["created"] is True
        assert created["location"].name == KNOWN_DISPLAY
        assert created["location"].alerting_enabled is True

        again = subscribe_address(user, KNOWN_QUERY)
        assert again["status"] == "ok"
        assert again["created"] is False
        assert UserLocation.query.filter_by(user_id=user.id).count() == 1


def test_subscribe_address_no_match(app):
    from coverage_subscribe import subscribe_address

    with app.app_context():
        user = _make_user(app)
        out = subscribe_address(user, NO_MATCH_QUERY)
        assert out == {"status": "no_match"}
        assert UserLocation.query.filter_by(user_id=user.id).count() == 0


def test_subscribe_address_respects_location_limit(app, monkeypatch):
    from coverage_subscribe import subscribe_address

    monkeypatch.setattr("coverage_subscribe._MAX_LOCATIONS_PER_USER", 1)
    with app.app_context():
        user = _make_user(app)
        assert subscribe_address(user, KNOWN_QUERY)["created"] is True
        limited = subscribe_address(user, OTHER_QUERY)
        assert limited["status"] == "limit_reached"
        assert limited["limit"] == 1
        assert UserLocation.query.filter_by(user_id=user.id).count() == 1


def test_subscribe_address_outside_pl(app, monkeypatch):
    from coverage_subscribe import subscribe_address

    monkeypatch.setattr(
        "app._resolve_address_coverage",
        lambda q: {"status": "outside_pl", "match": {"display": q}},
    )
    with app.app_context():
        user = _make_user(app)
        out = subscribe_address(user, "Somewhere abroad")
        assert out["status"] == "outside_pl"
        assert UserLocation.query.filter_by(user_id=user.id).count() == 0


# ── real5g_delta classifier ──────────────────────────────────────────────

def _snap(*bands):
    """bands: (band_code, has_coverage) tuples → _coverage_to_dict shape."""
    return {
        "gaps": [
            {"band": b, "has_coverage": cov, "nearest_distance_km": 0.5}
            for b, cov in bands
        ]
    }


def test_real5g_delta_flags_gain():
    from coverage_subscribe import real5g_delta
    before = _snap(("5G2100", True), ("LTE800", True))
    after = _snap(("5G2100", True), ("LTE800", True), ("5G3600", True))
    out = real5g_delta(before, after)
    assert out["gained"] is True
    assert out["lost"] is False
    assert out["gained_bands"] == ["5G3600"]
    assert out["lost_bands"] == []


def test_real5g_delta_flags_loss():
    from coverage_subscribe import real5g_delta
    before = _snap(("5G3600", True))
    after = _snap(("5G2100", True))
    out = real5g_delta(before, after)
    assert out["lost"] is True
    assert out["gained"] is False
    assert out["lost_bands"] == ["5G3600"]


def test_real5g_delta_no_change():
    from coverage_subscribe import real5g_delta
    snap = _snap(("5G3600", True), ("LTE2600", True))
    out = real5g_delta(snap, snap)
    assert out == {"gained": False, "lost": False,
                   "gained_bands": [], "lost_bands": []}


def test_real5g_delta_ignores_uncovered_and_sub_threshold():
    from coverage_subscribe import real5g_delta
    before = _snap()
    # 3600 present but NOT covered; 2100 covered but below the 3400 floor.
    after = _snap(("5G3600", False), ("5G2100", True))
    out = real5g_delta(before, after)
    assert out["gained"] is False
    assert out["gained_bands"] == []


def test_real5g_delta_handles_none_snapshots():
    from coverage_subscribe import real5g_delta
    assert real5g_delta(None, _snap(("5G3700", True)))["gained"] is True
    assert real5g_delta(_snap(("5G3700", True)), None)["lost"] is True
