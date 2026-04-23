"""Station data routes: /submit_location, /stations, /find_station, /search_stations.

Test-DB hubs (see scripts/generate_test_db.py):
- Warszawa  ~52.2297, 21.0122
- Kraków    ~50.0647, 19.9450
- Gdańsk    ~54.3520, 18.6466
"""
import json
import pytest

pytestmark = pytest.mark.integration

WARSAW = (52.2297, 21.0122)


# ── /submit_location ────────────────────────────────────────────────────────

def _post_json(client, path, body, csrf_token=None):
    headers = {"Content-Type": "application/json"}
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    return client.post(path, data=json.dumps(body), headers=headers)


def test_submit_location_happy_path(csrf_client, csrf_token):
    r = _post_json(csrf_client, "/submit_location",
                   {"lat": WARSAW[0], "lng": WARSAW[1]}, csrf_token)
    assert r.status_code == 200
    body = r.get_json()
    assert "stations" in body and "count" in body
    assert body["count"] > 0
    for s in body["stations"]:
        assert "basestation_id" in s
        assert isinstance(s["frequency_bands"], list)


def test_submit_location_without_csrf_rejected(client):
    r = _post_json(client, "/submit_location", {"lat": WARSAW[0], "lng": WARSAW[1]})
    assert r.status_code == 403


def test_submit_location_out_of_bounds(csrf_client, csrf_token):
    r = _post_json(csrf_client, "/submit_location", {"lat": 0.0, "lng": 0.0}, csrf_token)
    assert r.status_code == 400


def test_submit_location_missing_keys(csrf_client, csrf_token):
    r = _post_json(csrf_client, "/submit_location", {}, csrf_token)
    assert r.status_code == 400


def test_submit_location_invalid_types(csrf_client, csrf_token):
    r = _post_json(csrf_client, "/submit_location",
                   {"lat": "abc", "lng": "xyz"}, csrf_token)
    assert r.status_code == 400


@pytest.mark.parametrize("lat,lng,expected", [
    # PR #29 relaxed the strict PL bounds to ±0.05° (~5 km buffer) so
    # a user clicking just over a border isn't abruptly 400'd.
    # Strict PL corners still pass.
    (49.0, 14.0, 200),    # south-west corner (strict PL)
    (55.5, 24.2, 200),    # north-east corner (strict PL)
    # Inside the 5-km buffer → accepted.
    (48.96, 14.0, 200),   # 4 km south of strict PL
    (55.54, 24.0, 200),   # 4 km north of strict PL
    # Outside the buffer → rejected.
    (48.90, 14.0, 400),   # too far south
    (55.60, 24.0, 400),   # too far north
    (52.0, 13.90, 400),   # too far west
    (52.0, 24.30, 400),   # too far east
])
def test_submit_location_boundary_coords(csrf_client, csrf_token, lat, lng, expected):
    r = _post_json(csrf_client, "/submit_location",
                   {"lat": lat, "lng": lng}, csrf_token)
    assert r.status_code == expected


# ── /stations ────────────────────────────────────────────────────────────────

def test_stations_no_session_no_query(client):
    r = client.get("/stations")
    assert r.status_code == 400


def test_stations_with_lat_lng_query(client):
    r = client.get(f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=5")
    assert r.status_code == 200
    body = r.get_json()
    assert "stations" in body and len(body["stations"]) > 0
    assert len(body["stations"]) <= 5


def test_stations_filter_by_provider(client):
    r = client.get(
        f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=10"
        "&service_provider=Orange Polska S.A."
    )
    assert r.status_code == 200
    for s in r.get_json()["stations"]:
        assert s["service_provider"] == "Orange Polska S.A."


def test_stations_filter_by_band_and_provider_combined(client):
    """Combined filter previously had no test coverage."""
    r = client.get(
        f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=10"
        "&service_provider=Orange Polska S.A."
        "&frequency_bands=LTE1800"
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["count"] >= 1
    for s in body["stations"]:
        assert s["service_provider"] == "Orange Polska S.A."
        assert "LTE1800" in s["frequency_bands"]


def test_stations_invalid_limit(client):
    r = client.get(f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=100")
    assert r.status_code == 400


def test_stations_invalid_max_distance(client):
    r = client.get(f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&max_distance=50")
    assert r.status_code == 400


@pytest.mark.parametrize("max_dist,expected", [
    (0.099, 400),   # below boundary
    (0.1, 200),     # boundary low
    (10.0, 200),    # boundary high
    (10.001, 400),  # above boundary
])
def test_stations_max_distance_boundaries(client, max_dist, expected):
    r = client.get(
        f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&max_distance={max_dist}"
    )
    assert r.status_code == expected


def test_stations_out_of_bounds(client):
    r = client.get("/stations?lat=10.0&lng=10.0")
    assert r.status_code == 400


def test_stations_empty_result_returns_200_not_500(client):
    """Far from any test fixture station — must be graceful empty list,
    not error. Critical for the 'no embarrassing thin coverage' UX goal."""
    # Pick a corner of the supported area with no stations in our fixture
    r = client.get(f"/stations?lat=49.5&lng=22.0&max_distance=0.1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["count"] == 0
    assert body["stations"] == []


# ── /find_station ───────────────────────────────────────────────────────────

def test_find_station_existing_returns_200(client):
    """Test fixture seeded basestation_ids T1000+ — pick one."""
    r = client.get("/find_station?basestation_id=T1000")
    assert r.status_code == 200
    body = r.get_json()
    assert body["basestation_id"] == "T1000"
    assert "latitude" in body and "longitude" in body


def test_find_station_nonexistent_returns_404(client):
    r = client.get("/find_station?basestation_id=ZZZZZ")
    assert r.status_code == 404


def test_find_station_invalid_chars(client):
    r = client.get("/find_station?basestation_id=<script>")
    assert r.status_code == 400


def test_find_station_too_long(client):
    r = client.get("/find_station?basestation_id=TOOLONGID")
    assert r.status_code == 400


def test_find_station_missing_param(client):
    r = client.get("/find_station")
    assert r.status_code == 400


# ── /search_stations ─────────────────────────────────────────────────────────

def test_search_stations_prefix_match(client):
    r = client.get("/search_stations?q=T10")
    assert r.status_code == 200
    body = r.get_json()
    assert "stations" in body
    assert len(body["stations"]) > 0
    for s in body["stations"]:
        assert s["basestation_id"].startswith("T10")


def test_search_stations_case_insensitive(client):
    r = client.get("/search_stations?q=t10")  # lower case
    assert r.status_code == 200
    body = r.get_json()
    # Backend uppercases query → still matches T10xx fixture rows
    assert len(body["stations"]) > 0


def test_search_stations_too_short(client):
    r = client.get("/search_stations?q=T")
    assert r.status_code == 200
    assert r.get_json()["stations"] == []


def test_search_stations_invalid_chars(client):
    r = client.get("/search_stations?q=<script>")
    assert r.status_code == 200
    assert r.get_json()["stations"] == []


def test_search_stations_respects_limit(client):
    r = client.get("/search_stations?q=T1&limit=3")
    assert r.status_code == 200
    assert len(r.get_json()["stations"]) <= 3
