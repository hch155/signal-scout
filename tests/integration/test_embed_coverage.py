"""Embeddable coverage-card widget surface."""
import dataclasses

import pytest

pytestmark = pytest.mark.integration

CARD_URL = "/embed/coverage"
DISCLAIMER_FRAGMENT = "Szacowane na podstawie lokalizacji nadajników UKE"


def test_card_renders_inside_frame(client):
    r = client.get(CARD_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/html")
    body = r.get_data(as_text=True)
    assert "cc-card" in body
    assert "Bardzo dobry" in body
    assert DISCLAIMER_FRAGMENT in body
    # auto-resize script is referenced as an external 'self' script (CSP-safe)
    assert 'src="/embed/coverage.js' in body
    assert 'data-embed-frame="1"' in body


def test_card_is_publicly_cacheable(client):
    r = client.get(CARD_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert "public" in r.headers.get("Cache-Control", "")


def test_default_csp_blocks_framing(client):
    r = client.get(CARD_URL, query_string={"q": "Marszałkowska Warszawa"})
    csp = r.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_frame_ancestors_honors_allowed_origins(client, monkeypatch):
    import app as app_module

    replaced = dataclasses.replace(
        app_module.settings, embed_allowed_origins_raw="https://partner.example"
    )
    monkeypatch.setattr(app_module, "settings", replaced)

    r = client.get(CARD_URL, query_string={"q": "Marszałkowska Warszawa"})
    csp = r.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors https://partner.example" in csp
    assert "frame-ancestors 'none'" not in csp
    assert "X-Frame-Options" not in r.headers


def test_no_match_renders_message_card(client):
    r = client.get(CARD_URL, query_string={"q": "Qwerty Asdfgh"})
    assert r.status_code == 200
    assert "Nie znaleziono adresu" in r.get_data(as_text=True)


def test_too_short_query_is_rejected(client):
    r = client.get(CARD_URL, query_string={"q": "ab"})
    assert r.status_code == 400


def test_address_is_html_escaped(client, monkeypatch):
    payload = "<script>alert('xss')</script>"
    monkeypatch.setattr(
        "embed_coverage_routes.search_addresses",
        lambda *a, **k: [{"display": payload, "lat": 52.2297, "lng": 21.0122}],
    )
    r = client.get(CARD_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert payload not in body
    assert "&lt;script&gt;" in body


def test_loader_served_as_javascript(client):
    r = client.get("/embed/coverage.js")
    assert r.status_code == 200
    assert "javascript" in r.headers.get("Content-Type", "")
    cache = r.headers.get("Cache-Control", "")
    assert "public" in cache and "max-age=" in cache
    body = r.get_data(as_text=True)
    assert "signal-scout-embed-height" in body
    assert "/embed/coverage" in body


def test_builder_renders_form(client):
    r = client.get("/embed/coverage/builder")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "/embed/coverage.js" in body
    assert 'name="address"' in body


def test_builder_generates_snippet(client):
    r = client.get("/embed/coverage/builder", query_string={"address": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "data-address=" in body
    assert "Marszałkowska Warszawa" in body
    assert "/embed/coverage.js" in body
