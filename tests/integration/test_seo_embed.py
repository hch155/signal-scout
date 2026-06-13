"""SEO + embed widget surface (PR #10)."""
import re
import json as _json
import pytest

pytestmark = pytest.mark.integration


# ── robots.txt ──────────────────────────────────────────────────────────────

def test_robots_txt_served(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers.get("Content-Type", "").startswith("text/plain")
    body = r.data.decode("utf-8")
    assert "User-agent: *" in body
    assert "Allow: /" in body
    assert "Disallow: /api/" in body
    assert "Disallow: /embed/" in body
    assert "Sitemap:" in body


def test_robots_blocks_internal_routes(client):
    body = client.get("/robots.txt").data.decode("utf-8")
    for forbidden in ("/account", "/login", "/register", "/metrics",
                      "/healthz", "/find_station", "/search_stations",
                      "/stations", "/submit_location", "/session_check"):
        assert f"Disallow: {forbidden}" in body, f"crawler rule missing for {forbidden}"


# ── sitemap.xml ─────────────────────────────────────────────────────────────

def test_sitemap_xml_served(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in r.headers.get("Content-Type", "")
    body = r.data.decode("utf-8")
    assert body.startswith('<?xml version="1.0"')
    for path in ("/", "/data", "/stats", "/tips"):
        # canonical_origin defaults to https://www.signal-scout.com
        assert f"www.signal-scout.com{path}" in body


# ── Per-page SEO meta ───────────────────────────────────────────────────────

@pytest.mark.parametrize("path,unique_substr", [
    ("/", "Find the Nearest Cellular"),
    ("/data", "Network Data — Frequency Bands"),
    ("/stats", "Polish Mobile Network Statistics"),
    ("/tips", "Tips: Boost Your Cellular Signal"),
])
def test_per_page_titles(client, path, unique_substr):
    # Per-page SEO titles matter in production (that's what crawlers index);
    # in dev/staging the title is a short "[DEV] Signal-Scout" environment
    # marker by design, so assert the production behavior here.
    app = client.application
    prev = app.jinja_env.globals.get('app_env')
    app.jinja_env.globals['app_env'] = 'production'
    try:
        r = client.get(path)
        assert r.status_code == 200
        body = r.data.decode("utf-8")
        m = re.search(r'<title>([^<]+)</title>', body)
        assert m and unique_substr in m.group(1), \
            f"{path} title doesn't contain {unique_substr!r}: {m and m.group(1)!r}"
    finally:
        app.jinja_env.globals['app_env'] = prev


def test_meta_description_per_page(client):
    for path in ("/", "/data", "/stats", "/tips"):
        body = client.get(path).data.decode("utf-8")
        assert '<meta name="description"' in body, f"{path} missing description"


def test_canonical_url_per_page(client):
    for path in ("/", "/data", "/stats", "/tips"):
        body = client.get(path).data.decode("utf-8")
        assert f'href="https://www.signal-scout.com{path}"' in body, \
            f"{path} canonical wrong"


def test_open_graph_tags_present(client):
    body = client.get("/").data.decode("utf-8")
    assert 'property="og:title"' in body
    assert 'property="og:description"' in body
    assert 'property="og:image"' in body
    assert 'property="og:url"' in body
    assert 'property="og:site_name" content="Signal-Scout"' in body


def test_twitter_card_tags_present(client):
    body = client.get("/").data.decode("utf-8")
    assert 'name="twitter:card" content="summary_large_image"' in body
    assert 'name="twitter:title"' in body
    assert 'name="twitter:image"' in body


def test_jsonld_structured_data_on_home(client):
    body = client.get("/").data.decode("utf-8")
    m = re.search(
        r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
        body, re.DOTALL,
    )
    assert m, "JSON-LD block not found"
    data = _json.loads(m.group(1))
    assert data["@context"] == "https://schema.org"
    assert data["@type"] == "WebApplication"
    assert "Signal-Scout" in data["name"]


# ── /embed/widget ───────────────────────────────────────────────────────────

def test_embed_widget_default_renders(client):
    r = client.get("/embed/widget")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'id="embed-map"' in body
    assert 'Powered by Signal-Scout' in body
    # No coords supplied → "Show stations near you?" prompt visible
    assert 'Show stations near you?' in body


def test_embed_widget_with_coords(client):
    r = client.get("/embed/widget?lat=52.23&lng=21.00&zoom=13&limit=3")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'DEFAULT_LAT = 52.23' in body
    assert 'DEFAULT_LNG = 21' in body         # Jinja float renders 21.0 as 21
    assert 'DEFAULT_ZOOM = 13' in body
    assert 'LIMIT = 3' in body
    # Coords supplied → no auto-prompt
    assert 'Show stations near you?' not in body


def test_embed_widget_invalid_coords(client):
    r = client.get("/embed/widget?lat=abc&lng=xyz")
    assert r.status_code == 400


def test_embed_widget_out_of_bounds_coords(client):
    r = client.get("/embed/widget?lat=10&lng=10")
    assert r.status_code == 400


def test_embed_robots_noindex(client):
    body = client.get("/embed/widget").data.decode("utf-8")
    # Embed shouldn't be indexed by search engines
    assert 'name="robots" content="noindex,nofollow"' in body


# ── frame-ancestors header behavior ─────────────────────────────────────────

def test_default_csp_blocks_framing(client):
    r = client.get("/")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_embed_with_no_allowed_origins_still_blocks(client, monkeypatch):
    """If EMBED_ALLOWED_ORIGINS is unset, /embed/* still 200s but framing
    is still blocked — defense-in-depth (the embed endpoint is also useful
    as a same-origin partial)."""
    monkeypatch.delenv("EMBED_ALLOWED_ORIGINS", raising=False)
    # Recreate settings to pick up env change; in tests the singleton was
    # frozen at import time, so just check the default behavior.
    r = client.get("/embed/widget?lat=52.23&lng=21.00")
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_embed_permissions_policy_allows_geolocation(client):
    r = client.get("/embed/widget")
    pp = r.headers.get("Permissions-Policy", "")
    assert "geolocation=*" in pp
    # Other policies stay locked
    assert "camera=()" in pp
    assert "microphone=()" in pp


def test_main_app_permissions_policy_locks_geolocation_to_self(client):
    r = client.get("/")
    pp = r.headers.get("Permissions-Policy", "")
    assert "geolocation=(self)" in pp


# ── Image optimization ─────────────────────────────────────────────────────

def test_rate_limit_image_lazy_loaded(client):
    body = client.get("/").data.decode("utf-8")
    # Modal img should be lazy + decoding=async (not blocking initial paint)
    assert 'src="/static/limitexceededfresh.png"' in body
    assert 'loading="lazy"' in body
    assert 'decoding="async"' in body
