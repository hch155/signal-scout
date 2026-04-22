"""OpenAPI / Swagger UI surface (PR #6)."""
import json
import pytest

pytestmark = pytest.mark.integration


def test_openapi_spec_served(client):
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("Content-Type", "")
    spec = json.loads(r.data)
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"] == "Signal-Scout Public API"


def test_openapi_lists_only_versioned_paths(client):
    spec = json.loads(client.get("/api/v1/openapi.json").data)
    paths = set(spec["paths"].keys())
    expected = {
        "/api/v1/stations",
        "/api/v1/find_station",
        "/api/v1/search_stations",
        "/api/v1/submit_location",
        "/api/v1/healthz",
    }
    assert expected.issubset(paths), f"missing paths: {expected - paths}"
    # Internal endpoints must NOT appear in the public API spec
    for forbidden in ("/login", "/register", "/logout", "/account",
                      "/metrics", "/stats", "/data", "/tips"):
        assert forbidden not in paths


def test_openapi_declares_security_schemes(client):
    spec = json.loads(client.get("/api/v1/openapi.json").data)
    schemes = spec["components"]["securitySchemes"]
    assert "ApiKeyAuth" in schemes
    assert schemes["ApiKeyAuth"]["in"] == "header"
    assert schemes["ApiKeyAuth"]["name"] == "X-API-Key"


def test_openapi_declares_station_schema(client):
    spec = json.loads(client.get("/api/v1/openapi.json").data)
    station = spec["components"]["schemas"]["Station"]
    assert "basestation_id" in station["properties"]
    assert "service_provider" in station["properties"]
    # Provider enum locked to the four real Polish operators
    enum = station["properties"]["service_provider"]["enum"]
    assert "Orange Polska S.A." in enum
    assert "T-Mobile Polska S.A." in enum


def test_swagger_ui_renders(client):
    r = client.get("/api/v1/docs/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")
    body = r.data.decode("utf-8")
    assert "swagger-ui" in body.lower()


def test_api_v1_stations_works_with_referer(client):
    r = client.get("/api/v1/stations?lat=52.2297&lng=21.0122&limit=3")
    assert r.status_code == 200
    body = r.get_json()
    assert "stations" in body and body["count"] > 0


def test_api_v1_stations_blocked_without_referer(raw_client):
    r = raw_client.get("/api/v1/stations?lat=52.2297&lng=21.0122&limit=3")
    assert r.status_code == 403


def test_api_v1_find_station_works(client):
    r = client.get("/api/v1/find_station?basestation_id=T1000")
    assert r.status_code == 200
    body = r.get_json()
    assert body["basestation_id"] == "T1000"


def test_api_v1_search_stations_works(client):
    r = client.get("/api/v1/search_stations?q=T10")
    assert r.status_code == 200
    body = r.get_json()
    assert "stations" in body


def test_api_v1_healthz_works(client):
    r = client.get("/api/v1/healthz")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_legacy_paths_still_work_for_back_compat(client):
    """The /api/v1/ rollout must not break the unprefixed routes that
    browser JS currently calls — back-compat is the whole point."""
    assert client.get("/stations?lat=52.23&lng=21.00&limit=3").status_code == 200
    assert client.get("/find_station?basestation_id=T1000").status_code == 200
    assert client.get("/search_stations?q=T10").status_code == 200
    assert client.get("/healthz").status_code == 200


def test_api_v1_submit_location_with_csrf(csrf_client, csrf_token):
    """Versioned POST still requires CSRF (we just route to the same handler)."""
    r = csrf_client.post(
        "/api/v1/submit_location",
        data=json.dumps({"lat": 52.2297, "lng": 21.0122}),
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf_token},
    )
    assert r.status_code == 200


def test_api_v1_submit_location_without_csrf_blocked(client):
    r = client.post(
        "/api/v1/submit_location",
        data=json.dumps({"lat": 52.2297, "lng": 21.0122}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 403
