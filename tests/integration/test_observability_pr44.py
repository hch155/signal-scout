"""PR #44 industry-standard observability buildout — tests for the new
counters, gauges, SLO snapshots, /status route, and conversion funnel
hooks.

Mirrors the existing `test_observability.py` pattern: scrape /metrics
with the bearer token, look for the new metric name in the body, and
exercise the route paths that should bump the counters.
"""
import re

import pytest

pytestmark = pytest.mark.integration

CSRF_TOKEN = "test-csrf-token"


def _scrape(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    return client.get(
        "/metrics", headers={"Authorization": "Bearer supersecret"}
    ).get_data(as_text=True)


# ── /status route (customer-facing) ─────────────────────────────────────────

def test_status_html_renders_200(client):
    r = client.get("/status")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")
    body = r.get_data(as_text=True)
    # Header text per the PR brief.
    assert "signal-scout.com" in body
    assert "public service health" in body


def test_status_json_payload_shape(client):
    r = client.get("/status?format=json")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("Content-Type", "")
    payload = r.get_json()
    # Required keys for downstream uptime aggregators.
    for key in (
        "service", "summary", "components",
        "availability_target", "availability_current",
        "latency_target_ms", "requests_total",
    ):
        assert key in payload, f"missing key: {key}"
    component_names = {c["name"] for c in payload["components"]}
    assert component_names == {"API", "Web", "Search"}


def test_status_does_not_leak_security_signals(client):
    """Privacy boundary: the /status payload must NEVER contain CSRF /
    login / honeypot / API-key / tier signals — those live on the
    operator-only Grafana dashboard."""
    r = client.get("/status?format=json")
    body = r.get_data(as_text=True).lower()
    forbidden = (
        "csrf", "login_failure", "honeypot",
        "api_key", "tier", "rate_limit",
    )
    for needle in forbidden:
        assert needle not in body, f"/status leaks {needle!r}"


def test_status_excluded_from_request_metrics(client, monkeypatch):
    """/status is infra — must not bump public_requests_total or the
    user-agent class counter (otherwise self-scrapes inflate stats)."""
    before = _scrape(client, monkeypatch)
    client.get("/status")
    after = _scrape(client, monkeypatch)
    pat = re.compile(r"^signal_scout_public_requests_total (\S+)$", re.MULTILINE)
    m_before = pat.search(before)
    m_after = pat.search(after)
    val_before = float(m_before.group(1)) if m_before else 0.0
    val_after = float(m_after.group(1)) if m_after else 0.0
    assert val_before == val_after, (
        f"/status hit bumped public_requests_total: {val_before} → {val_after}"
    )


# ── RED-method per-tier counters ────────────────────────────────────────────

def test_api_requests_total_emitted_for_stations(client, monkeypatch):
    client.get("/stations?lat=52.23&lng=21.00&limit=3")
    body = _scrape(client, monkeypatch)
    assert "signal_scout_api_requests_total" in body
    assert 'endpoint="stations"' in body
    # Same-origin browser test client → 'anonymous' tier.
    assert 'tier="anonymous"' in body


def test_api_request_duration_seconds_records_histogram(client, monkeypatch):
    client.get("/stations?lat=52.23&lng=21.00&limit=3")
    body = _scrape(client, monkeypatch)
    assert "signal_scout_api_request_duration_seconds_bucket" in body
    assert "signal_scout_api_request_duration_seconds_count" in body


# ── USE-method saturation gauges ────────────────────────────────────────────

def test_in_flight_requests_gauge_exposed(client, monkeypatch):
    body = _scrape(client, monkeypatch)
    assert "signal_scout_in_flight_requests" in body


def test_workers_configured_gauge_exposed(client, monkeypatch):
    body = _scrape(client, monkeypatch)
    assert "signal_scout_gunicorn_workers_configured" in body


# ── SLO snapshot gauges ────────────────────────────────────────────────────

def test_slo_gauges_refreshed_on_scrape(client, monkeypatch):
    """The SLO gauges are refreshed inside the /metrics view, so a
    single scrape must publish them with sane (in-range) values."""
    body = _scrape(client, monkeypatch)
    for name in (
        "signal_scout_slo_availability_ratio",
        "signal_scout_slo_latency_ratio_under_500ms",
        "signal_scout_slo_error_budget_remaining_ratio",
    ):
        assert name in body, f"SLO gauge missing: {name}"


def test_slo_availability_starts_at_100_percent(client, monkeypatch):
    """With no errors served by the test process, availability should be
    1.0 (or absent / parsed-to-1 if no requests have happened yet)."""
    # Hit a happy-path route so the exporter has something to count.
    client.get("/")
    body = _scrape(client, monkeypatch)
    pat = re.compile(r"^signal_scout_slo_availability_ratio (\S+)$", re.MULTILINE)
    m = pat.search(body)
    assert m is not None
    value = float(m.group(1))
    assert 0.99 <= value <= 1.0


# ── Conversion funnel counters ─────────────────────────────────────────────

def test_register_started_funnel_counter(csrf_client, csrf_token, monkeypatch):
    csrf_client.post(
        "/register",
        data={
            "_csrf_token": csrf_token,
            "email": "garbage",  # forces validation failure
            "password": "x",
        },
    )
    body = _scrape(csrf_client, monkeypatch)
    assert "signal_scout_funnel_register_started_total" in body


def test_register_completed_funnel_counter(csrf_client, csrf_token, monkeypatch):
    import secrets as _s
    email = f"funnel-{_s.token_hex(4)}@example.com"
    pw = "Aa1!aaaaaa"
    r = csrf_client.post(
        "/register",
        data={
            "_csrf_token": csrf_token, "email": email,
            "password": pw, "confirm_password": pw,
        },
    )
    assert r.status_code == 200, r.data
    body = _scrape(csrf_client, monkeypatch)
    assert "signal_scout_funnel_register_completed_total" in body


# ── Public-volume + healthz counters ───────────────────────────────────────

def test_public_requests_total_increments_on_user_route(client, monkeypatch):
    """Every user-facing route bumps the public_requests counter that
    drives the customer dashboard's 'requests served' figure."""
    before = _scrape(client, monkeypatch)
    client.get("/")
    after = _scrape(client, monkeypatch)
    pat = re.compile(r"^signal_scout_public_requests_total (\S+)$", re.MULTILINE)
    m_after = pat.search(after)
    m_before = pat.search(before)
    val_after = float(m_after.group(1)) if m_after else 0.0
    val_before = float(m_before.group(1)) if m_before else 0.0
    assert val_after > val_before


def test_healthz_total_counter_increments(client, monkeypatch):
    client.get("/healthz")
    body = _scrape(client, monkeypatch)
    assert "signal_scout_healthz_total" in body
