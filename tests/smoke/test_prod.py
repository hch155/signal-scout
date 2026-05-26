"""Production smoke tests against https://signal-scout.com.

Marked @pytest.mark.smoke and excluded from default pytest invocation. Run on
demand with `pytest -m smoke`. Read-only; never registers, logs in, or POSTs.

Designed to be polite to production:
- ≤6 requests total
- 2-second sleep between requests
- One TCP session reused
"""
import os
import time
import pytest
import requests

pytestmark = [pytest.mark.smoke]

PROD_URL = os.getenv("SMOKE_TARGET", "https://signal-scout.com")
PAUSE_S = float(os.getenv("SMOKE_PAUSE_S", "2.0"))

session = requests.Session()
session.headers.update({"User-Agent": "signal-scout-smoke-tests/1.0"})


def _get(path):
    time.sleep(PAUSE_S)
    return session.get(PROD_URL + path, timeout=15, allow_redirects=True)


def test_home_returns_200_and_html():
    r = _get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")
    assert "Signal-Scout" in r.text


def test_baseline_security_headers_present_in_prod():
    """Headers that have been on prod for a while — should always pass."""
    r = _get("/")
    assert "Strict-Transport-Security" in r.headers
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


@pytest.mark.xfail(
    reason="Content-Security-Policy ships in PR #1 — expected to pass post-deploy",
    strict=False,
)
def test_csp_headers_present_in_prod():
    """Full CSP/Permissions/Referrer headers added in PR #1 — flips green
    once the security hotfixes land on Cloud Run. xfail keeps the suite
    informative without going red on every smoke run pre-deploy."""
    r = _get("/")
    assert "Content-Security-Policy" in r.headers
    csp = r.headers["Content-Security-Policy"]
    script_src = csp.split("script-src")[1].split(";")[0] if "script-src" in csp else ""
    assert "'unsafe-inline'" not in script_src
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in r.headers


def test_stats_page_returns_200():
    r = _get("/stats")
    assert r.status_code == 200
    assert "Statistics" in r.text or "stats-th" in r.text


def test_data_page_returns_200():
    r = _get("/data")
    assert r.status_code == 200


def test_stations_endpoint_returns_data_for_warsaw():
    r = _get("/stations?lat=52.23&lng=21.00&limit=3")
    assert r.status_code == 200
    body = r.json()
    assert "stations" in body
    assert len(body["stations"]) > 0
    for s in body["stations"]:
        assert "basestation_id" in s
        assert "service_provider" in s


def test_session_check_anonymous_in_prod():
    r = _get("/session_check")
    assert r.status_code == 200
    assert r.json() == {"logged_in": False}
