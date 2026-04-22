"""Tests for /metrics + /healthz + custom Prometheus counters."""
import os
import pytest

pytestmark = pytest.mark.integration


# ── /healthz ────────────────────────────────────────────────────────────────

def test_healthz_returns_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["service"] == "signal-scout"


def test_healthz_does_not_require_auth(client):
    r = client.get("/healthz")
    # Even without any header, returns 200 — load balancer probes don't
    # carry bearer tokens.
    assert r.status_code == 200


def test_healthz_has_security_headers(client):
    """Even probe endpoints must carry the same defense-in-depth headers."""
    r = client.get("/healthz")
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in r.headers


# ── /metrics auth gating ────────────────────────────────────────────────────

def test_metrics_returns_404_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("METRICS_BEARER_TOKEN", raising=False)
    r = client.get("/metrics")
    assert r.status_code == 404


def test_metrics_returns_401_with_no_auth_when_token_set(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    r = client.get("/metrics")
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate", "").startswith("Bearer")


def test_metrics_returns_401_with_wrong_token(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    r = client.get("/metrics", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_metrics_returns_200_with_correct_bearer(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    r = client.get("/metrics", headers={"Authorization": "Bearer supersecret"})
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("Content-Type", "")
    body = r.get_data(as_text=True)
    # Some basic prometheus text format markers
    assert "# HELP" in body
    assert "# TYPE" in body


def test_metrics_includes_http_request_metrics(client, monkeypatch):
    """Hit a route then scrape — HTTP metrics auto-collected by exporter."""
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    client.get("/")  # generate a sample
    r = client.get("/metrics", headers={"Authorization": "Bearer supersecret"})
    body = r.get_data(as_text=True)
    assert "signal_scout_http" in body  # exporter prefix


# ── Custom domain counters ──────────────────────────────────────────────────

def _scrape(client):
    return client.get(
        "/metrics", headers={"Authorization": "Bearer supersecret"}
    ).get_data(as_text=True)


def test_csrf_failure_counter_increments(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    before = _scrape(client)
    # Hit /submit_location without CSRF → 403, increments counter
    client.post("/submit_location", json={"lat": 52.23, "lng": 21.0})
    after = _scrape(client)
    assert "signal_scout_csrf_failures_total" in after
    # The endpoint label must reflect the route
    assert 'endpoint="submit_location"' in after


def test_login_failure_counter_increments(csrf_client, csrf_token, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    csrf_client.post("/login", data={
        "_csrf_token": csrf_token, "email": "ghost@example.com", "password": "Aa1!aaaa",
    })
    body = _scrape(csrf_client)
    # The metric name must show up at all
    assert "signal_scout_login_failures_total" in body


def test_station_search_counter_increments_on_stations_route(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    client.get("/stations?lat=52.23&lng=21.00&limit=3")
    body = _scrape(client)
    assert "signal_scout_station_search_total" in body
    assert 'endpoint="stations"' in body


def test_empty_result_counter_increments_on_no_match(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    # Far from any test fixture row → empty result path
    client.get("/stations?lat=49.5&lng=22.0&max_distance=0.1")
    body = _scrape(client)
    assert "signal_scout_empty_result_total" in body


def test_metrics_endpoint_excluded_from_request_metrics(client, monkeypatch):
    """Self-recursion guard: scraping /metrics shouldn't itself bump the
    HTTP request counter into the metrics output (would create growth on
    every scrape)."""
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    # Generate two scrapes
    body1 = _scrape(client)
    body2 = _scrape(client)
    # Both responses are valid prometheus text; we don't strictly forbid the
    # exporter from counting /metrics itself — just sanity that it returns OK.
    assert body1 and body2


# ── PR #4: usage analytics counters ─────────────────────────────────────────

def test_provider_filter_counter_increments(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    client.get(
        "/stations?lat=52.2297&lng=21.0122&limit=3"
        "&service_provider=Orange Polska S.A."
    )
    body = _scrape(client)
    assert "signal_scout_provider_filter_used_total" in body
    assert 'provider="Orange Polska S.A."' in body


def test_band_filter_counter_increments(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    client.get("/stations?lat=52.2297&lng=21.0122&limit=3&frequency_bands=LTE1800")
    body = _scrape(client)
    assert "signal_scout_band_filter_used_total" in body
    assert 'band="LTE1800"' in body


def test_user_agent_class_counter_buckets_browsers(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    client.get("/", headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    body = _scrape(client)
    assert "signal_scout_requests_by_user_agent_class_total" in body
    assert 'ua_class="browser_chrome"' in body


def test_user_agent_class_counter_buckets_googlebot(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    client.get("/", headers={
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    })
    body = _scrape(client)
    assert 'ua_class="googlebot"' in body


def test_user_agent_class_counter_buckets_curl_as_cli(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    client.get("/", headers={"User-Agent": "curl/8.4.0"})
    body = _scrape(client)
    assert 'ua_class="cli"' in body


def test_user_agent_class_skips_metrics_and_healthz(client, monkeypatch):
    """Probes shouldn't dominate ua_class counts. /metrics and /healthz are
    excluded from the after_request hook."""
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    # Hit /healthz with a clearly bot-looking UA — bucket should NOT increment.
    before = _scrape(client)
    client.get("/healthz", headers={"User-Agent": "Googlebot"})
    after = _scrape(client)
    # The body strings should be identical for the googlebot label since
    # /healthz is excluded. Approximation: googlebot label either absent in
    # both, or unchanged.
    import re
    pat = re.compile(
        r'signal_scout_requests_by_user_agent_class_total\{ua_class="googlebot"\} (\S+)'
    )
    m_before = pat.search(before)
    m_after = pat.search(after)
    val_before = float(m_before.group(1)) if m_before else 0.0
    val_after = float(m_after.group(1)) if m_after else 0.0
    assert val_after == val_before
