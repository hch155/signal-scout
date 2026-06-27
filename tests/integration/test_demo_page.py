"""GET /demo — the B2B live-API demo page.

The page is a thin shell registered by `marketing_routes.register_marketing_routes`
and gated by the same MARKETING_ENABLED flag as /pricing. app.py wires it at
boot, but the test harness imports app.py without the flag set, so we register
the route on the shared app fixture here (idempotently) and flip the flag with
the same bound-reference monkeypatch dance the marketing/admin suite uses.
"""
import dataclasses

import pytest

pytestmark = pytest.mark.integration


def _register(app):
    import marketing_routes
    if "demo_page" not in app.view_functions:
        marketing_routes.register_marketing_routes(app)


def _patch_marketing(monkeypatch, enabled: bool):
    import app as app_mod
    import config as config_mod
    import marketing_routes
    new_settings = dataclasses.replace(app_mod.settings, marketing_enabled=enabled)
    monkeypatch.setattr(marketing_routes, "settings", new_settings)
    monkeypatch.setattr(app_mod, "settings", new_settings)
    monkeypatch.setattr(config_mod, "settings", new_settings)


@pytest.fixture
def demo_off(app, monkeypatch):
    _register(app)
    _patch_marketing(monkeypatch, False)
    yield


@pytest.fixture
def demo_on(app, monkeypatch):
    _register(app)
    _patch_marketing(monkeypatch, True)
    yield


def test_demo_returns_404_when_marketing_off(client, demo_off):
    r = client.get("/demo")
    assert r.status_code == 404
    assert r.get_json()["error"] == "not_found"


def test_demo_renders_when_marketing_on(client, demo_on):
    r = client.get("/demo")
    assert r.status_code == 200
    assert b'id="api-demo"' in r.data


def test_demo_embeds_curl_with_api_key_placeholder(client, demo_on):
    body = client.get("/demo").data.decode("utf-8")
    assert "X-API-Key: YOUR_API_KEY" in body
    assert "/api/v1/coverage_by_address?q=" in body


def test_demo_links_to_swagger_pricing_and_contact(client, demo_on):
    body = client.get("/demo").data.decode("utf-8")
    assert "/api/v1/docs/" in body          # Swagger UI (api_docs.py)
    assert 'href="/pricing"' in body
    assert "/contact?plan=pro" in body      # B2B CTA


def test_demo_loads_its_page_script(client, demo_on):
    body = client.get("/demo").data.decode("utf-8")
    assert "dist/pages/api-demo.min.js" in body


def test_demo_composes_live_coverage_endpoint(client, demo_on):
    """The endpoints the page calls from the browser must work under the
    same-origin anonymous tier (the `client` fixture injects a Referer)."""
    r = client.get("/coverage_by_address", query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    assert r.get_json()["coverage"]["signal_tier"] == "Excellent"

    card = client.get("/coverage_card", query_string={"q": "Marszałkowska Warszawa"})
    assert card.status_code == 200
    assert "text/html" in card.headers["Content-Type"]
