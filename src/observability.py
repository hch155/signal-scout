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

import os
import time
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
)

gunicorn_workers_configured = Gauge(
    "signal_scout_gunicorn_workers_configured",
    "Number of gunicorn workers configured for this process. Read once "
    "from the WORKERS env at boot. Pair with in_flight_requests for the "
    "USE-method utilisation ratio (in_flight / workers).",
)

slo_availability_ratio = Gauge(
    "signal_scout_slo_availability_ratio",
    "Current availability SLI: 1 - (5xx_count / total_count) over the "
    "in-process counter window. Target ≥ 0.995 (99.5%). Computed on "
    "every /metrics scrape from the auto-collected HTTP counters.",
)

slo_latency_ratio_under_500ms = Gauge(
    "signal_scout_slo_latency_ratio_under_500ms",
    "Current latency SLI for /stations: fraction of api_request_duration "
    "samples below the 500 ms bucket. Target ≥ 0.95. Computed on every "
    "/metrics scrape.",
)

slo_error_budget_remaining_ratio = Gauge(
    "signal_scout_slo_error_budget_remaining_ratio",
    "Fraction of the 0.5% error budget still un-burned, in [0, 1]. "
    "0 means budget exhausted (alert). Derived from "
    "slo_availability_ratio with a 99.5% target.",
)

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


# ── In-memory tracking for /status incident timestamp ──────────────────────

_LAST_INCIDENT_TS: dict[str, float] = {"value": 0.0}
_FIRST_CALL_SEEN_USERS: set[int] = set()


def record_first_api_call(user_id: int | None) -> None:
    """Best-effort: bump the funnel counter the first time a user_id is
    seen on the API path within the current process."""
    if user_id is None:
        return
    if user_id in _FIRST_CALL_SEEN_USERS:
        return
    _FIRST_CALL_SEEN_USERS.add(user_id)
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
    """Length-leaking? Yes. Constant-time across same-length strings."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


def _build_metrics_view(token_env_var: str) -> Callable[[], Response]:
    """Bearer-token protected /metrics view."""

    def metrics_view() -> Response:
        configured = os.getenv(token_env_var, "").strip()
        if not configured:
            return Response("Not Found", status=404)
        provided = _bearer_token_from_request()
        if not provided or not _constant_time_eq(provided, configured):
            return Response("Unauthorized", status=401,
                            headers={"WWW-Authenticate": 'Bearer realm="metrics"'})
        # PR #44: refresh SLO gauges on every scrape.
        try:
            _refresh_slo_gauges()
        except Exception:
            pass
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    return metrics_view


def init_observability(app: Flask, token_env_var: str = "METRICS_BEARER_TOKEN") -> None:
    """Wire Prometheus + /healthz onto the Flask app."""
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

    @app.route("/healthz", methods=["GET"])
    def healthz():
        try:
            healthz_total.inc()
        except Exception:
            pass
        return jsonify({
            "status": "ok",
            "service": "signal-scout",
            "version": os.getenv("APP_VERSION", "dev"),
        }), 200


def record_compute_time(func):
    """Decorator that records find_nearest_stations() execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        with nearest_stations_compute_seconds.time():
            return func(*args, **kwargs)
    return wrapper


