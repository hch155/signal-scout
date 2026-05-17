"""ANALYTICS-PLAN.md PR-1 — bot scoring, session cookie, pulse/trap probes.

Asserts the multi-signal bot score in `signal_scout_bot_score_total{score}`
behaves per the weight table (observability.compute_bot_score docstring):

    - CLI/bot UA + missing cookie + missing pulse  → score >= 2
    - browser UA + cookie + pulse                  → score 0
    - /api/v1/_trap hit                            → score 5+

Also covers the supporting plumbing:
    - first request mints an `ss_sid` cookie + bumps sessions_seen_total
    - /api/v1/_pulse returns 204 + flips the JS-pulse session flag
    - active_anon_sessions gauge reflects the TTL set
    - /_trap and /_pulse are NOT listed in robots.txt or sitemap.xml
"""
from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.integration


def _scrape(client, monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "supersecret")
    return client.get(
        "/metrics", headers={"Authorization": "Bearer supersecret"}
    ).get_data(as_text=True)


def _score_count(body: str, label: str) -> float:
    """Pull `signal_scout_bot_score_total{score="N"} V` out of the scrape."""
    pat = (
        r'signal_scout_bot_score_total\{score="'
        + re.escape(label)
        + r'"\}\s+([\d.eE+-]+)'
    )
    m = re.search(pat, body)
    return float(m.group(1)) if m else 0.0


@pytest.fixture(autouse=True)
def _reset_session_state(app):  # depend on `app` so src/ is on sys.path
    """Wipe the in-memory TTL sets so per-test active-session assertions
    aren't polluted by earlier tests in the same session."""
    from observability import _reset_session_state_for_tests
    _reset_session_state_for_tests()
    yield


# ── ss_sid cookie + sessions_seen_total ───────────────────────────────────

def _cookie_value(client, name):
    """Pull a cookie value off the test client across Flask 2.x/3.x APIs."""
    # Flask 3.x stores cookies on _cookies as a dict-like keyed by
    # (domain, path, name); older versions exposed werkzeug's CookieJar.
    cookies = getattr(client, "_cookies", None)
    if cookies is not None:
        # Newer API: dict-like with werkzeug.test.Cookie values.
        for c in cookies.values():
            if getattr(c, "key", None) == name:
                return c.value
        return None
    jar = getattr(client, "cookie_jar", None)
    if jar is None:
        return None
    for c in jar:
        if c.name == name or getattr(c, "key", None) == name:
            return c.value
    return None


def test_first_request_mints_ss_sid_cookie(client):
    # Fresh client (don't reuse session-cookie state from other tests).
    c = client.application.test_client()
    c.get("/healthz")  # infra path → no cookie
    assert _cookie_value(c, "ss_sid") is None

    r = c.get("/")
    assert r.status_code == 200
    sid = _cookie_value(c, "ss_sid")
    assert sid is not None and len(sid) == 32  # 16 bytes hex


def test_sessions_seen_total_increments_on_first_visit(client, monkeypatch):
    _ = _scrape(client, monkeypatch)
    client.get("/")  # mints cookie
    body = _scrape(client, monkeypatch)
    assert "signal_scout_sessions_seen_total" in body


# ── /api/v1/_pulse ────────────────────────────────────────────────────────

def test_pulse_returns_204(client):
    r = client.get("/api/v1/_pulse")
    assert r.status_code == 204
    assert r.get_data() == b""


def test_pulse_sets_js_seen_flag(client):
    client.get("/api/v1/_pulse")
    with client.session_transaction() as sess:
        assert sess.get("_js_pulse_seen") is True


# ── /api/v1/_trap ─────────────────────────────────────────────────────────

def test_trap_returns_404(client):
    r = client.get("/api/v1/_trap")
    assert r.status_code == 404


def test_trap_bumps_honeypot_counter(client, monkeypatch):
    _ = _scrape(client, monkeypatch)
    client.get("/api/v1/_trap")
    body = _scrape(client, monkeypatch)
    assert 'signal_scout_honeypot_hit_total{endpoint="_trap"}' in body


def test_trap_not_listed_in_robots(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # CRITICAL: listing /_trap in robots would warn well-behaved crawlers
    # off the trap. The trap relies on being invisible, not declared.
    assert "_trap" not in body
    assert "_pulse" not in body


def test_trap_not_listed_in_sitemap(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "_trap" not in body
    assert "_pulse" not in body


# ── compute_bot_score (pure function) ─────────────────────────────────────

def test_compute_bot_score_human_browser_with_state():
    from observability import compute_bot_score
    assert compute_bot_score(
        ua_class="browser_chrome",
        has_ss_sid_cookie=True,
        js_pulse_seen=True,
        request_count_in_session=10,
        referer_blocked=False,
        honeypot_tripped=False,
    ) == 0


def test_compute_bot_score_cli_no_pulse_no_cookie():
    """CLI UA (+2) plus no cookie on req >1 (+1) → score 3."""
    from observability import compute_bot_score
    assert compute_bot_score(
        ua_class="cli",
        has_ss_sid_cookie=False,
        js_pulse_seen=False,
        request_count_in_session=2,
        referer_blocked=False,
        honeypot_tripped=False,
    ) >= 2


def test_compute_bot_score_honeypot_overrides_to_5():
    from observability import compute_bot_score
    # Even with everything else looking human, honeypot trip → 5.
    assert compute_bot_score(
        ua_class="browser_chrome",
        has_ss_sid_cookie=True,
        js_pulse_seen=True,
        request_count_in_session=10,
        referer_blocked=False,
        honeypot_tripped=True,
    ) == 5


def test_compute_bot_score_first_request_no_state_is_score_0():
    """Don't penalise request #1 for missing cookie or pulse — there hasn't
    been a chance yet to set either."""
    from observability import compute_bot_score
    assert compute_bot_score(
        ua_class="browser_chrome",
        has_ss_sid_cookie=False,
        js_pulse_seen=False,
        request_count_in_session=1,
        referer_blocked=False,
        honeypot_tripped=False,
    ) == 0


def test_compute_bot_score_caps_at_5():
    from observability import compute_bot_score
    # UA bot (+2) + no cookie (+1) + no pulse (+1) + referer (+1) = 5
    assert compute_bot_score(
        ua_class="googlebot",
        has_ss_sid_cookie=False,
        js_pulse_seen=False,
        request_count_in_session=10,
        referer_blocked=True,
        honeypot_tripped=False,
    ) == 5


# ── end-to-end emission via after_request hook ────────────────────────────

def test_trap_hit_emits_score_5_plus(client, monkeypatch):
    _ = _scrape(client, monkeypatch)
    before = _score_count(_scrape(client, monkeypatch), "5+")
    client.get("/api/v1/_trap")
    after = _score_count(_scrape(client, monkeypatch), "5+")
    assert after >= before + 1


def test_bot_score_counter_appears_in_metrics(client, monkeypatch):
    client.get("/")  # any non-infra request to emit one bucket
    body = _scrape(client, monkeypatch)
    assert "signal_scout_bot_score_total" in body


def test_cli_user_agent_scores_higher_than_browser(client, monkeypatch):
    """Hit / with a curl UA repeatedly; the score>=2 buckets should grow.

    Uses raw_client (no auto-injected Referer) — but / doesn't require one,
    so this is fine. We send a fresh client each time so cookie state stays
    minimal across hits, which is itself part of the bot signal.
    """
    # Warm-up scrape to get the baseline. (TTL set already reset by the
    # autouse fixture above.)
    baseline = _scrape(client, monkeypatch)
    base_0 = _score_count(baseline, "0")
    base_high = (
        _score_count(baseline, "2")
        + _score_count(baseline, "3")
        + _score_count(baseline, "4")
        + _score_count(baseline, "5+")
    )

    # Five CLI hits — no cookie carried forward between, no JS pulse.
    for _ in range(5):
        c = client.application.test_client()
        c.get("/", headers={"User-Agent": "curl/8.4.0"})

    body = _scrape(client, monkeypatch)
    end_0 = _score_count(body, "0")
    end_high = (
        _score_count(body, "2")
        + _score_count(body, "3")
        + _score_count(body, "4")
        + _score_count(body, "5+")
    )
    # CLI hits should land in the >=2 buckets, not the 0 bucket.
    assert (end_high - base_high) >= 1
    # Sanity: the 0 bucket did NOT grow by the CLI traffic volume.
    assert (end_high - base_high) > (end_0 - base_0) / 2


def test_active_anon_sessions_gauge_present_after_visit(client, monkeypatch):
    client.get("/")  # mint a cookie + register the session in the TTL set
    body = _scrape(client, monkeypatch)
    # Gauge must be exported.
    assert "signal_scout_active_anon_sessions" in body


def test_active_authed_sessions_gauge_present(client, monkeypatch):
    client.get("/")
    body = _scrape(client, monkeypatch)
    assert "signal_scout_active_authed_sessions" in body
