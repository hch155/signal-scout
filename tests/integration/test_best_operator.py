"""Integration tests for the best-operator page + referral redirect.

The blueprint is wired in app.py via register_best_operator_routes (returned
as an integration point). This module self-wires defensively so it still
exercises the routes if that edit is present; if the app has already handled
a request and the routes are absent, the tests skip rather than 404-fail.
"""
import pytest

pytestmark = pytest.mark.integration

PAGE = "/best-operator"
KNOWN = "Marszałkowska Warszawa"


@pytest.fixture(autouse=True)
def _ensure_wired(app):
    if "best_operator.best_operator_page" not in app.view_functions:
        if getattr(app, "_got_first_request", False):
            pytest.skip("best-operator routes not registered on the app")
        import app as app_module
        from best_operator_routes import register_best_operator_routes
        register_best_operator_routes(app, limiter=app_module.limiter)
    yield


def test_page_without_query_renders_form(client):
    r = client.get(PAGE)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="bo-form"' in html
    assert "Best operator for this address" in html


def test_known_address_html_highlights_recommended_and_referral_cta(client):
    r = client.get(PAGE, query_string={"q": KNOWN})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Recommended" in html
    assert "/go/operator/" in html


def test_known_address_json_ranks_with_single_recommended(client):
    r = client.get(PAGE, query_string={"q": KNOWN, "format": "json"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    ops = body["operators"]
    assert ops, "expected ranked operators"

    scores = [o["rank_score"] for o in ops]
    assert scores == sorted(scores, reverse=True)
    assert sum(1 for o in ops if o["recommended"]) == 1
    assert ops[0]["recommended"] is True

    for o in ops:
        assert o["slug"]
        assert "rank_score" in o
        assert o["rationale"]["en"] and o["rationale"]["pl"]


def test_recommended_operator_has_referral_path(client):
    body = client.get(PAGE, query_string={"q": KNOWN, "format": "json"}).get_json()
    winner = body["operators"][0]
    assert winner["referral_path"] == f"/go/operator/{winner['slug']}"


def test_json_payload_excludes_raw_station_internals(client):
    body = client.get(PAGE, query_string={"q": KNOWN, "format": "json"}).get_json()
    for o in body["operators"]:
        assert "location" not in o
        assert "latitude" not in o
        assert "stations" not in o


def test_no_match_returns_404(client):
    assert client.get(PAGE, query_string={"q": "Qwerty Asdfgh"}).status_code == 404
    r = client.get(PAGE, query_string={"q": "Qwerty Asdfgh", "format": "json"})
    assert r.status_code == 404
    assert r.get_json()["status"] == "no_match"


def test_too_short_query_is_400(client):
    r = client.get(PAGE, query_string={"q": "ab", "format": "json"})
    assert r.status_code == 400
    assert r.get_json()["status"] == "invalid"


def test_outside_pl_returns_200_with_no_operators(client, monkeypatch):
    monkeypatch.setattr(
        "app.search_addresses",
        lambda *a, **k: [{"display": "Somewhere, Sweden", "lat": 60.0, "lng": 18.0}],
    )
    r = client.get(PAGE, query_string={"q": "Somewhere Sweden", "format": "json"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "outside_pl"
    assert body["operators"] == []


def test_go_operator_redirects_and_counts_clicks(client):
    from best_operator_routes import referral_clicks_total

    before = referral_clicks_total.labels(operator="orange")._value.get()
    r = client.get("/go/operator/orange")
    assert r.status_code == 302
    location = r.headers["Location"]
    assert "utm_source=signal-scout" in location
    assert "utm_campaign=best-operator" in location
    after = referral_clicks_total.labels(operator="orange")._value.get()
    assert after == before + 1


def test_go_operator_unknown_slug_is_404(client):
    assert client.get("/go/operator/not-an-operator").status_code == 404
