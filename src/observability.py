"""Prometheus instrumentation for signal-scout.

Design choices:
- Built-in HTTP request metrics (status, latency, count) come for free from
  prometheus_flask_exporter. No need to instrument routes by hand.
- Domain counters (CSRF failures, login failures, 429s, search queries)
  are explicit Counters defined here and incremented from app.py.
- /metrics is bearer-token protected ONLY if METRICS_BEARER_TOKEN is set.
  When unset, /metrics returns 404 — refusing to expose metrics rather than
  serving them publicly. Cloud Run is internet-facing, so an unauthenticated
  /metrics would leak rate-limit budgets and per-route latency to anyone.
- /healthz is always available, takes no auth, returns 200 with a small JSON
  body. Used by Cloud Run / load balancers / uptime checks.

PR #44 industry-standard observability layer
--------------------------------------------
Three frameworks layered on top of the existing counters:

- **Four Golden Signals** (Google SRE book, ch.6):
      Latency · Traffic · Errors · Saturation
- **RED method** (Rate / Errors / Duration), per resource — Weaveworks.
  `signal_scout_api_requests_total{tier,endpoint,outcome}` rolls up
  Rate + Errors per tier so the dashboard can answer "are pro tier
  customers getting more 5xx than free?".
- **USE method** (Utilisation / Saturation / Errors of resources) —
  Brendan Gregg. In-process gauges for in-flight requests + worker
  count.
- **SLI/SLO**: two SLIs are tracked in-process so we don't depend on a
  long PromQL retention window:
      SLI-1 availability  = 1 - (5xx / total)            target 99.5%
      SLI-2 latency       = fraction of /stations < 500 ms over the
                            in-process histogram          target 95%
- **Public status page** (`/status`): consumes the same in-process
  counters via `compute_public_status()` below. Customer-facing — only
  "is it up?", "is it fast?", "how many requests per day?". No
  security signals (CSRF / honeypot / login / API keys / tier counts)
  ever cross to that surface.
"""

from __future__ import annotations

import hmac
import os
import time
from collections import OrderedDict
from functools import wraps
from typing import Callable

from flask import Flask, Response, jsonify, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_flask_exporter import PrometheusMetrics


# ── Custom domain counters ──────────────────────────────────────────────────

csrf_failures_total = Counter(
    "signal_scout_csrf_failures_total",
    "POST requests rejected due to missing or mismatched CSRF token.",
    labelnames=("endpoint",),
)

login_failures_total = Counter(
    "signal_scout_login_failures_total",
    "Failed /login attempts (unknown user OR wrong password).",
)

rate_limit_hits_total = Counter(
    "signal_scout_rate_limit_hits_total",
    "Requests that hit the Flask-Limiter rate limit (HTTP 429).",
    labelnames=("endpoint",),
)

station_search_total = Counter(
    "signal_scout_station_search_total",
    "Station search requests served, by endpoint.",
    labelnames=("endpoint",),
)

provider_filter_used_total = Counter(
    "signal_scout_provider_filter_used_total",
    "Number of /stations queries filtering by a specific service provider.",
    labelnames=("provider",),
)

band_filter_used_total = Counter(
    "signal_scout_band_filter_used_total",
    "Number of /stations queries filtering by a specific frequency band.",
    labelnames=("band",),
)

compass_used_total = Counter(
    "signal_scout_compass_used_total",
    "Compass-mode activation count (mobile users navigating to a station).",
)

requests_by_user_agent_class_total = Counter(
    "signal_scout_requests_by_user_agent_class_total",
    "HTTP requests classified by user-agent bucket.",
    labelnames=("ua_class",),
)

api_referer_blocked_total = Counter(
    "signal_scout_api_referer_blocked_total",
    "API requests rejected because they had no API key AND no same-origin "
    "Referer/Origin header — strong scraping signal.",
    labelnames=("endpoint",),
)

api_key_used_total = Counter(
    "signal_scout_api_key_used_total",
    "API requests authorized via X-API-Key (or browser session), labelled "
    "by tier.",
    labelnames=("tier",),
)

honeypot_hit_total = Counter(
    "signal_scout_honeypot_hit_total",
    "Lookups against fake basestation IDs reserved as scrape tripwires. "
    "Any non-zero value is alert-worthy.",
    labelnames=("endpoint",),
)


_BOT_UA_PATTERNS = (
    ("googlebot", "googlebot"),
    ("bingbot", "bingbot"),
    ("yandex", "other_bot"),
    ("baiduspider", "other_bot"),
    ("duckduckbot", "other_bot"),
    ("slurp", "other_bot"),
    ("applebot", "other_bot"),
    ("facebookexternalhit", "other_bot"),
    ("twitterbot", "other_bot"),
    ("ahrefsbot", "other_bot"),
    ("semrushbot", "other_bot"),
    ("mj12bot", "other_bot"),
    ("dotbot", "other_bot"),
    ("petalbot", "other_bot"),
    ("uptimerobot", "other_bot"),
    ("pingdom", "other_bot"),
    ("bot", "other_bot"),
    ("crawler", "other_bot"),
    ("spider", "other_bot"),
)

_CLI_UA_PREFIXES = ("curl/", "wget/", "python-requests/", "go-http-client/", "okhttp/", "java/", "httpx/")


def classify_user_agent(ua: str | None) -> str:
    """Bucket a User-Agent string into one of ~9 low-cardinality classes."""
    if not ua:
        return "unknown"
    lower = ua.lower()

    for needle, bucket in _BOT_UA_PATTERNS:
        if needle in lower:
            return bucket

    if any(lower.startswith(p) for p in _CLI_UA_PREFIXES):
        return "cli"

    if "edg/" in lower or "edge/" in lower:
        return "browser_other"
    if "firefox/" in lower:
        return "browser_firefox"
    if "chrome/" in lower or "chromium/" in lower:
        return "browser_chrome"
    if "safari/" in lower:
        return "browser_safari"

    return "unknown"

empty_result_total = Counter(
    "signal_scout_empty_result_total",
    "Successful station-fetch responses that returned zero stations "
    "(useful for spotting clients sitting in coverage holes).",
)

nearest_stations_compute_seconds = Histogram(
    "signal_scout_nearest_stations_compute_seconds",
    "Time spent inside find_nearest_stations() (seconds).",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


# ── PR #44: RED + USE + SLI/SLO + funnel + public-status metrics ───────────

api_requests_total = Counter(
    "signal_scout_api_requests_total",
    "RED-method counter for the public read API: total requests broken "
    "down by (tier, endpoint, outcome). Outcome buckets: success (2xx), "
    "client_error (4xx), server_error (5xx). Combine with rate() for "
    "RPS or use the {outcome=\"server_error\"} subset for the error "
    "ratio.",
    labelnames=("tier", "endpoint", "outcome"),
)

api_request_duration_seconds = Histogram(
    "signal_scout_api_request_duration_seconds",
    "RED/Golden-Signals duration histogram for the public read API, "
    "labelled by endpoint. Use histogram_quantile(0.50/0.95/0.99, ...) "
    "to derive p50 / p95 / p99 in Grafana.",
    labelnames=("endpoint",),
    buckets=(
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
    ),
)

in_flight_requests = Gauge(
    "signal_scout_in_flight_requests",
    "USE-method saturation gauge: number of HTTP requests currently "
    "being served. Compare against the gunicorn worker count "
    "(WORKERS env, default 2) — sustained values near WORKERS mean "
    "saturation, queueing, and rising tail latency.",
    multiprocess_mode="max"
)

gunicorn_workers_configured = Gauge(
    "signal_scout_gunicorn_workers_configured",
    "Number of gunicorn workers configured for this process. Read once "
    "from the WORKERS env at boot. Pair with in_flight_requests for the "
    "USE-method utilisation ratio (in_flight / workers).",
    multiprocess_mode="max"
)

slo_availability_ratio = Gauge(
    "signal_scout_slo_availability_ratio",
    "Current availability SLI: 1 - (5xx_count / total_count) over the "
    "in-process counter window. Target ≥ 0.995 (99.5%). Computed on "
    "every /metrics scrape from the auto-collected HTTP counters.",
    multiprocess_mode="max"
)

slo_latency_ratio_under_500ms = Gauge(
    "signal_scout_slo_latency_ratio_under_500ms",
    "Current latency SLI for /stations: fraction of api_request_duration "
    "samples below the 500 ms bucket. Target ≥ 0.95. Computed on every "
    "/metrics scrape.",
    multiprocess_mode="max"
)

slo_error_budget_remaining_ratio = Gauge(
    "signal_scout_slo_error_budget_remaining_ratio",
    "Fraction of the 0.5% error budget still un-burned, in [0, 1]. "
    "0 means budget exhausted (alert). Derived from "
    "slo_availability_ratio with a 99.5% target.",
    multiprocess_mode="max"
)

# ── Per-endpoint HTTP funnel (added 2026-04-28) ───────────────────────────

http_requests_total = Counter(
    "signal_scout_http_requests_total",
    "All HTTP requests served by the app, broken down by route + "
    "status bucket + user class. Method label kept too so GET vs "
    "POST splits aren't lost. user_class one of: 'anon' (no session, "
    "no API key), 'session' (logged-in via cookie), 'api_free' / "
    "'api_pro' / 'api_enterprise' (X-API-Key authenticated, by tier).",
    labelnames=("method", "endpoint", "status", "user_class"),
)

http_request_duration_seconds = Histogram(
    "signal_scout_http_request_duration_seconds",
    "Duration histogram for every HTTP route. Companion to "
    "http_requests_total — use histogram_quantile for p50/p95/p99 "
    "per endpoint in Grafana. Buckets cover the typical 5ms..10s "
    "Cloud Run response shape.",
    labelnames=("method", "endpoint"),
    buckets=(
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
    ),
)

user_action_total = Counter(
    "signal_scout_user_action_total",
    "High-level user actions completed successfully, broken down by "
    "action name and user class. Action vocabulary: "
    "submit_location, location_create, location_delete, "
    "location_snapshot, register, login_password, login_oauth, "
    "logout, totp_setup, totp_disable, api_key_create, "
    "api_key_revoke, account_delete. Use rate() for activity per "
    "minute, sum by (action) for global tallies.",
    labelnames=("action", "user_class"),
)


def request_user_class() -> str:
    """Bucket the current request into a user_class label value.

    Reads flask.g.api_key_tier (set by api_access middleware when an
    X-API-Key header authenticated the request) before falling back
    to session.get('user_id'). Anonymous browser requests → 'anon'.
    Best-effort — never raises, returns 'anon' on any unexpected
    state."""
    try:
        from flask import g, session
        tier = getattr(g, 'api_key_tier', None)
        if tier:
            return f"api_{tier}"
        if session.get('user_id'):
            return 'session'
    except Exception:
        pass
    return 'anon'


funnel_register_started_total = Counter(
    "signal_scout_funnel_register_started_total",
    "Conversion funnel step 1: POST /register attempts (any outcome). "
    "Denominator for the 'register success rate' KPI.",
)

funnel_register_completed_total = Counter(
    "signal_scout_funnel_register_completed_total",
    "Conversion funnel step 2: successful /register (HTTP 200). "
    "Numerator for register success rate; denominator for "
    "'first API key created' below.",
)

funnel_first_api_key_created_total = Counter(
    "signal_scout_funnel_first_api_key_created_total",
    "Conversion funnel step 3: a user created their FIRST extra API "
    "key via /account/keys (the auto-key from registration doesn't "
    "count here — this measures intent to actually use the API).",
)

funnel_first_api_call_total = Counter(
    "signal_scout_funnel_first_api_call_total",
    "Conversion funnel step 4: a user's API key has been used at least "
    "once on /stations or /find_station. Best-effort — only the first "
    "call per process lifetime increments to keep cardinality bounded.",
)

healthz_total = Counter(
    "signal_scout_healthz_total",
    "Total /healthz probes served (always 200). Used by the customer-"
    "facing /status page to compute uptime% over the last 24h/7d.",
)

public_requests_total = Counter(
    "signal_scout_public_requests_total",
    "Public-facing request counter — counts every request that reached "
    "a user-visible route (excluding /metrics, /healthz, /status). "
    "Drives the 'requests served' figure on the customer dashboard.",
)


# ── 2026-04-29: extended observability surface ────────────────────────────

db_query_seconds = Histogram(
    "signal_scout_db_query_seconds",
    "SQLAlchemy query duration histogram, labelled by table. Wired via "
    "engine event listener (before_cursor_execute / after_cursor_execute) "
    "so any model query is captured. Use histogram_quantile for p50/p95/p99 "
    "per table — spotting query regressions when stations.db grows or "
    "after a refactor lands a hot loop.",
    labelnames=("table",),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

email_send_total = Counter(
    "signal_scout_email_send_total",
    "Outbound email attempts via emails._send. Labelled by template + "
    "outcome ('sent' | 'send_failed' | 'suppressed' | 'alerts_disabled' "
    "| 'no_user' | 'render_failed'). Pairs with email_event_total below "
    "(sent here = SendGrid accepted; delivered there = SendGrid actually "
    "handed off to recipient MTA).",
    labelnames=("template", "outcome"),
)

email_event_total = Counter(
    "signal_scout_email_event_total",
    "SendGrid Event Webhook receiver counter. event_type ∈ "
    "{processed, delivered, open, click, bounce, dropped, deferred, "
    "spamreport, unsubscribe, group_unsubscribe, group_resubscribe}. "
    "Bounce + spamreport rates are the deliverability KPI; sustained "
    "non-zero spamreport is sender-reputation territory.",
    labelnames=("event_type",),
)

active_users_24h = Gauge(
    "signal_scout_active_users_24h",
    "Distinct user_ids that took any logged user_action in the last 24h. "
    "Recomputed at every /metrics scrape via Gauge.set_function — DAU "
    "north star for product traction.",
    multiprocess_mode="max"
)

saved_locations_total = Gauge(
    "signal_scout_saved_locations_total",
    "Total UserLocation rows in the users.db. Recomputed at every /metrics "
    "scrape. Pairs with user_action_total{action='location_create'|'location_delete'} "
    "to spot a delete spike (churn) vs a create spike (engagement).",
    multiprocess_mode="max"
)

coverage_alert_sweep_seconds = Histogram(
    "signal_scout_coverage_alert_sweep_seconds",
    "Wall time of one full run_coverage_alert_sweep() invocation. The "
    "sweep walks every alerting-enabled UserLocation, computes a fresh "
    "find_coverage_gaps + diff, and sends emails. Cron-fired monthly by "
    "Cloud Scheduler — sustained high latency means we'll soon outgrow "
    "the 180s attempt-deadline.",
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 180.0),
)

coverage_alert_sweep_sent_total = Counter(
    "signal_scout_coverage_alert_sweep_sent_total",
    "Per-status counter for each location processed by a coverage-alert "
    "sweep. status ∈ {'first-run', 'no-change', 'sent', 'send-failed', "
    "'skipped'}. Lets Grafana plot 'how many real diff emails the last "
    "monthly run produced' vs noise.",
    labelnames=("status",),
)

coverage_alert_sweep_last_run_timestamp = Gauge(
    "signal_scout_coverage_alert_sweep_last_run_timestamp",
    "Unix timestamp of the last completed coverage-alert sweep. Alert "
    "(CoverageSweepStale) when now - this > 35 days — UKE refresh is "
    "monthly, so a gap means the wired CI job stopped firing or the runner "
    "is down. max-mode so multi-worker setups don't lose the latest stamp.",
    multiprocess_mode="max"
)

stations_db_age_seconds = Gauge(
    "signal_scout_stations_db_age_seconds",
    "now - mtime(stations.db). Recomputed at every /metrics scrape. Alert "
    "when > 35d (~5 weeks) — UKE refresh cadence is monthly, anything "
    "older than that means the monthly-db-update workflow is broken or "
    "we missed a release. NOTE: Docker COPY resets mtime to build time on "
    "every redeploy, so this is also bounded by deploy cadence — re-deploys "
    "without a fresh DB will reset the age clock.",
    multiprocess_mode="max"
)

app_version_info = Gauge(
    "signal_scout_app_version_info",
    "Static gauge holding the deployed APP_VERSION as a label, value "
    "always 1. `signal_scout_app_version_info{version='2026.04.29-abc1234'} "
    "1`. Lets Grafana annotation queries correlate latency / error spikes "
    "with deploy boundaries — pin a vertical line every time the version "
    "label flips.",
    labelnames=("version",),
    multiprocess_mode="max"
)


# ── Bot-score + session analytics ──

bot_score_total = Counter(
    "signal_scout_bot_score_total",
    "Composite multi-signal bot score per request, bucketed 0..5+. "
    "0 = looks human (browser UA, JS pulse seen, cookie persists). "
    "5+ = honeypot trip OR sum of UA-bot + missing-pulse + missing-cookie "
    "+ referer-block weights. Pair with rate() in Grafana to plot bot "
    "pressure over time without per-IP cardinality.",
    labelnames=("score",),
)


active_authed_sessions = Gauge(
    "signal_scout_active_authed_sessions",
    "Distinct logged-in user_ids seen in the last 15 minutes. In-memory "
    "TTL set; resets on cold start. Complements active_users_24h (which "
    "is sourced from SubmitLocationEvent only) by capturing any "
    "authenticated activity, not just location submissions.",
    multiprocess_mode="max",
)


# Bot-score weight table.
_BOT_WEIGHT_UA_BOT = 2
_BOT_WEIGHT_NO_COOKIE = 1
_BOT_WEIGHT_NO_PULSE = 1
_BOT_WEIGHT_REFERER_BLOCK = 1
_BOT_WEIGHT_HONEYPOT_OVERRIDE = 5  # forces score=5+ regardless of others
_BOT_PULSE_GRACE_REQUESTS = 3      # don't penalise no-pulse before req #4


def compute_bot_score(
    *,
    ua_class: str,
    has_ss_sid_cookie: bool,
    js_pulse_seen: bool,
    request_count_in_session: int,
    referer_blocked: bool,
    honeypot_tripped: bool,
) -> int:
    """Sum the weak bot signals into a 0..5 score, clamped.

    Pure function — no Flask/request access — so it's trivial to unit-test
    and to call from both the after_request hook and the /_trap view.
    """
    if honeypot_tripped:
        return 5
    score = 0
    if ua_class.endswith("bot") or ua_class == "cli":
        score += _BOT_WEIGHT_UA_BOT
    if not has_ss_sid_cookie and request_count_in_session > 1:
        score += _BOT_WEIGHT_NO_COOKIE
    if (not js_pulse_seen
            and request_count_in_session > _BOT_PULSE_GRACE_REQUESTS):
        score += _BOT_WEIGHT_NO_PULSE
    if referer_blocked:
        score += _BOT_WEIGHT_REFERER_BLOCK
    return min(score, 5)


def bot_score_label(score: int) -> str:
    """Bucket label: 5+ for anything 5 or higher, exact int otherwise."""
    if score >= 5:
        return "5+"
    return str(score)


# ── In-memory TTL set for active-session gauges ────────────────────────────

_ACTIVE_SESSION_TTL_SECONDS = 15 * 60
_ACTIVE_SESSION_CAP = 100_000
_ACTIVE_AUTHED_SESSIONS: "OrderedDict[int, float]" = OrderedDict()


def _ttl_touch(store: "OrderedDict", key, now: float) -> None:
    """Mark `key` as seen at `now`, evicting LRU if over cap."""
    if key in store:
        store.move_to_end(key)
    store[key] = now
    while len(store) > _ACTIVE_SESSION_CAP:
        store.popitem(last=False)


def _ttl_count(store: "OrderedDict", now: float) -> int:
    """Sweep entries older than the TTL, return live population."""
    cutoff = now - _ACTIVE_SESSION_TTL_SECONDS
    while store:
        oldest_key = next(iter(store))
        if store[oldest_key] < cutoff:
            store.popitem(last=False)
        else:
            break
    return len(store)


def record_authed_session_seen(user_id: int, now: float | None = None) -> None:
    """Bump the active-authed-sessions TTL set."""
    if user_id is None:
        return
    _ttl_touch(_ACTIVE_AUTHED_SESSIONS, user_id, now if now is not None else time.time())


def active_authed_session_count(now: float | None = None) -> int:
    return _ttl_count(_ACTIVE_AUTHED_SESSIONS, now if now is not None else time.time())


def _reset_session_state_for_tests() -> None:
    """Wipe the TTL set between tests so a 'new session' assertion is
    deterministic. Called from the integration test fixtures."""
    _ACTIVE_AUTHED_SESSIONS.clear()


# ── In-memory tracking for /status incident timestamp ──────────────────────

_LAST_INCIDENT_TS: dict[str, float] = {"value": 0.0}
_FIRST_CALL_LRU_CAP = 10_000
_FIRST_CALL_SEEN_USERS: "OrderedDict[int, None]" = None  # type: ignore[assignment]


def _ensure_first_call_lru():
    """Lazy-init the LRU map; structure stays None until first call so
    workers that never see API traffic don't allocate the dict."""
    global _FIRST_CALL_SEEN_USERS
    if _FIRST_CALL_SEEN_USERS is None:
        _FIRST_CALL_SEEN_USERS = OrderedDict()


def record_first_api_call(user_id: int | None) -> None:
    """Best-effort: bump the funnel counter the first time a user_id is
    seen on the API path within the current process. LRU-bounded so
    long-running workers don't accumulate state without limit."""
    if user_id is None:
        return
    _ensure_first_call_lru()
    if user_id in _FIRST_CALL_SEEN_USERS:
        # Mark as recently used so it survives eviction.
        _FIRST_CALL_SEEN_USERS.move_to_end(user_id)
        return
    _FIRST_CALL_SEEN_USERS[user_id] = None
    if len(_FIRST_CALL_SEEN_USERS) > _FIRST_CALL_LRU_CAP:
        _FIRST_CALL_SEEN_USERS.popitem(last=False)
    funnel_first_api_call_total.inc()


def record_incident(now: float | None = None) -> None:
    """Stamp the most-recent 5xx timestamp for the /status page."""
    _LAST_INCIDENT_TS["value"] = now if now is not None else time.time()


def last_incident_ts() -> float:
    return _LAST_INCIDENT_TS["value"]


# ── SLO snapshot computation ───────────────────────────────────────────────

SLO_AVAILABILITY_TARGET = 0.995          # 99.5% of requests must succeed
SLO_LATENCY_BUCKET_SECONDS = 0.5         # /stations under 500 ms
SLO_LATENCY_TARGET = 0.95                # 95% of /stations samples


def _walk_metric_samples(name_prefix: str):
    """Iterate (metric_name, labels, value) over every sample whose
    metric name starts with `name_prefix`."""
    for collector in list(REGISTRY._collector_to_names.keys()):
        for metric in collector.collect():
            if not metric.name.startswith(name_prefix):
                continue
            for sample in metric.samples:
                yield sample.name, sample.labels, sample.value


def _compute_availability_ratio() -> float:
    """SLI-1: 1 - (5xx / total) over the in-process exporter counter."""
    total = 0.0
    errors = 0.0
    for name, labels, value in _walk_metric_samples(
        "signal_scout_http_request_duration_seconds"
    ):
        if not name.endswith("_count"):
            continue
        total += value
        status = labels.get("status", "")
        if status.startswith("5"):
            errors += value
    if total <= 0:
        return 1.0
    return max(0.0, 1.0 - (errors / total))


def _compute_latency_ratio_under_500ms() -> float:
    """SLI-2: fraction of /stations samples in buckets ≤ 500 ms."""
    total = 0.0
    fast = 0.0
    for name, labels, value in _walk_metric_samples(
        "signal_scout_api_request_duration_seconds"
    ):
        if labels.get("endpoint") != "stations":
            continue
        if name.endswith("_count"):
            total = value
        elif name.endswith("_bucket"):
            try:
                le = float(labels.get("le", "+Inf"))
            except ValueError:
                continue
            if le <= SLO_LATENCY_BUCKET_SECONDS:
                if value > fast:
                    fast = value
    if total <= 0:
        return 1.0
    return min(1.0, fast / total)


def _refresh_slo_gauges() -> None:
    avail = _compute_availability_ratio()
    latency = _compute_latency_ratio_under_500ms()
    slo_availability_ratio.set(avail)
    slo_latency_ratio_under_500ms.set(latency)
    budget = 1.0 - SLO_AVAILABILITY_TARGET
    used = max(0.0, 1.0 - avail)
    if budget <= 0:
        remaining = 1.0
    else:
        remaining = max(0.0, 1.0 - (used / budget))
    slo_error_budget_remaining_ratio.set(remaining)


# ── Public status page payload ─────────────────────────────────────────────

def compute_public_status() -> dict:
    """Render-ready dict for the customer-facing /status page.

    Pulls live numbers straight from the in-process Prometheus registry
    so we don't double-source against Grafana / Prom on the NUC.

    Crucially: this NEVER returns counts of CSRF / login failures /
    honeypot hits / API keys / per-tier breakdown.
    """
    avail = _compute_availability_ratio()
    latency_ratio = _compute_latency_ratio_under_500ms()
    p50 = _quantile_from_buckets(0.5)
    p95 = _quantile_from_buckets(0.95)

    total_requests = 0.0
    for _name, _labels, value in _walk_metric_samples(
        "signal_scout_public_requests_total"
    ):
        if _name.endswith("_total") and not _name.endswith("_created_total"):
            total_requests += value

    api_status = "operational"
    if avail < 0.99:
        api_status = "degraded"
    if avail < 0.95:
        api_status = "down"

    search_status = "operational"
    if latency_ratio < 0.90:
        search_status = "degraded"
    if latency_ratio < 0.50:
        search_status = "down"

    web_status = "operational"
    return {
        "service": "signal-scout.com",
        "summary": (
            "All systems operational"
            if api_status == "operational" and search_status == "operational"
            else "Some systems degraded"
        ),
        "availability_target": SLO_AVAILABILITY_TARGET,
        "availability_current": avail,
        "latency_target_ms": int(SLO_LATENCY_BUCKET_SECONDS * 1000),
        "latency_p50_ms": int(p50 * 1000) if p50 else None,
        "latency_p95_ms": int(p95 * 1000) if p95 else None,
        "components": [
            {"name": "API",    "status": api_status},
            {"name": "Web",    "status": web_status},
            {"name": "Search", "status": search_status},
        ],
        "requests_total": int(total_requests),
        "last_incident_unix": last_incident_ts(),
    }


def _quantile_from_buckets(q: float) -> float | None:
    """Quantile estimate from the api_request_duration histogram."""
    buckets: list[tuple[float, float]] = []
    total = 0.0
    for name, labels, value in _walk_metric_samples(
        "signal_scout_api_request_duration_seconds"
    ):
        if name.endswith("_bucket"):
            try:
                le = float(labels.get("le", "+Inf"))
            except ValueError:
                continue
            buckets.append((le, value))
        elif name.endswith("_count"):
            total += value
    if total <= 0 or not buckets:
        return None
    agg: dict[float, float] = {}
    for le, v in buckets:
        agg[le] = agg.get(le, 0.0) + v
    sorted_buckets = sorted(agg.items())
    target = q * total
    for le, cum in sorted_buckets:
        if cum >= target:
            return le
    return sorted_buckets[-1][0]


def _bearer_token_from_request() -> str:
    """Extract bearer token from Authorization header, or empty string."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip()
    return ""


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


_DYNAMIC_GAUGE_REFRESHERS: list = []


def register_gauge_refresher(gauge, compute_fn) -> None:
    """Wired from app.py at boot; compute_fn() must return a float."""
    _DYNAMIC_GAUGE_REFRESHERS.append((gauge, compute_fn))


def _refresh_dynamic_gauges() -> None:
    for gauge, fn in _DYNAMIC_GAUGE_REFRESHERS:
        try:
            gauge.set(float(fn()))
        except Exception:
            pass  # leave previous value rather than zeroing on transient fail


def _build_metrics_view(token_env_var: str) -> Callable[[], Response]:
    """Bearer-token protected /metrics view.

    2026-04-29: when PROMETHEUS_MULTIPROC_DIR is set, build the response
    from a MultiProcessCollector that aggregates per-worker counter
    files in that dir. Otherwise (single-worker dev runs / tests),
    fall back to the default global registry.

    Without the multiproc path, gunicorn's --workers=2 fleet kept
    per-worker counter copies in process memory; a /metrics scrape
    landed on a random worker and returned only that one's counts —
    Prometheus saw the series jump up and down between scrapes and
    `increase(...)` returned 0. Multiproc fixes that with a SUM across
    all workers' files.
    """
    multiproc_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR", "").strip()

    def metrics_view() -> Response:
        configured = os.getenv(token_env_var, "").strip()
        if not configured:
            return Response("Not Found", status=404)
        provided = _bearer_token_from_request()
        if not provided or not _constant_time_eq(provided, configured):
            return Response("Unauthorized", status=401,
                            headers={"WWW-Authenticate": 'Bearer realm="metrics"'})
        try:
            _refresh_slo_gauges()
        except Exception:
            pass
        try:
            _refresh_dynamic_gauges()
        except Exception:
            pass

        if multiproc_dir:
            from prometheus_client import CollectorRegistry, multiprocess
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            return Response(generate_latest(registry),
                            mimetype=CONTENT_TYPE_LATEST)

        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    return metrics_view


def _ensure_multiproc_dir() -> None:
    """Make sure PROMETHEUS_MULTIPROC_DIR exists. NEVER cleans up
    existing .db files — that's a destructive op that has to happen
    BEFORE any Counter/Histogram is constructed (otherwise we wipe
    files prometheus_client opened at module import time, breaking
    every subsequent .inc()). Cleanup belongs in the gunicorn
    `on_starting` hook (gunicorn_conf.py), which runs in the master
    process before any worker fork."""
    d = os.getenv("PROMETHEUS_MULTIPROC_DIR", "").strip()
    if not d:
        return
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass


def init_observability(app: Flask, token_env_var: str = "METRICS_BEARER_TOKEN") -> None:
    """Wire Prometheus + /healthz onto the Flask app."""
    _ensure_multiproc_dir()

    PrometheusMetrics(
        app,
        path=None,
        defaults_prefix="signal_scout_http",
        group_by="endpoint",
    )

    app.add_url_rule(
        "/metrics", "metrics", _build_metrics_view(token_env_var), methods=["GET"]
    )

    # Seed the worker-count gauge at boot.
    try:
        gunicorn_workers_configured.set(int(os.getenv("WORKERS", "1")))
    except (TypeError, ValueError):
        gunicorn_workers_configured.set(1)

    def _healthz_view():
        try:
            healthz_total.inc()
        except Exception:
            pass
        return jsonify({
            "status": "ok",
            "service": "signal-scout",
            "version": os.getenv("APP_VERSION", "dev"),
        }), 200

    app.add_url_rule("/healthz", "healthz", _healthz_view, methods=["GET"])


def record_compute_time(func):
    """Decorator that records find_nearest_stations() execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        with nearest_stations_compute_seconds.time():
            return func(*args, **kwargs)
    return wrapper


