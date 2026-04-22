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
"""

from __future__ import annotations

import os
from functools import wraps
from typing import Callable

from flask import Flask, Response, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from prometheus_flask_exporter import PrometheusMetrics


# ── Custom domain counters ──────────────────────────────────────────────────
# Defined at module load so importers can `from observability import ...`.
# Kept narrow on purpose — every additional label combination is a separate
# time series in Prometheus, which costs cardinality.

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

# ── App-domain usage counters (what Plausible can't see) ────────────────────
# Plausible covers visitors, sources, pages. These cover *what users do
# inside the app* — bands/providers filtered, compass tapped — so the owner
# can decide which UI to invest in.

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

# ── User-agent class counter (low-cardinality bot/browser bucket) ───────────
# Raw User-Agent has unbounded cardinality — bucket into ~9 classes server-
# side and label by bucket only. Lets us alert on bot-traffic spikes and
# answer "is this growth real human visitors or scraping?".

requests_by_user_agent_class_total = Counter(
    "signal_scout_requests_by_user_agent_class_total",
    "HTTP requests classified by user-agent bucket.",
    labelnames=("ua_class",),
)


_BOT_UA_PATTERNS = (
    ("googlebot", "googlebot"),
    ("bingbot", "bingbot"),
    ("yandex", "other_bot"),
    ("baiduspider", "other_bot"),
    ("duckduckbot", "other_bot"),
    ("slurp", "other_bot"),         # Yahoo
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
    ("bot", "other_bot"),           # generic catch-all (also matches "robot")
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

    # Browser detection — order matters (Edge/Opera report Chrome, Chromium
    # reports Safari, etc.). Detect the more specific brand first.
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

# Histogram for the actual nearest-station compute time, separate from the
# wall-clock HTTP latency that the exporter already gives us.
nearest_stations_compute_seconds = Histogram(
    "signal_scout_nearest_stations_compute_seconds",
    "Time spent inside find_nearest_stations() (seconds).",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


def _bearer_token_from_request() -> str:
    """Extract bearer token from Authorization header, or empty string."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip()
    return ""


def _constant_time_eq(a: str, b: str) -> bool:
    """Length-leaking? Yes. Constant-time across same-length strings.
    Good enough for a fixed-length token comparison; avoid '==' which can
    short-circuit and leak token prefixes via timing."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


def _build_metrics_view(token_env_var: str) -> Callable[[], Response]:
    """Return a view function that serves /metrics, protected by an env-var
    bearer token. If the env var is unset (or empty), the view returns 404
    so external scrapers can't tell metrics exist at all."""

    def metrics_view() -> Response:
        configured = os.getenv(token_env_var, "").strip()
        if not configured:
            return Response("Not Found", status=404)
        provided = _bearer_token_from_request()
        if not provided or not _constant_time_eq(provided, configured):
            return Response("Unauthorized", status=401,
                            headers={"WWW-Authenticate": 'Bearer realm="metrics"'})
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    return metrics_view


def init_observability(app: Flask, token_env_var: str = "METRICS_BEARER_TOKEN") -> None:
    """Wire Prometheus + /healthz onto the Flask app.

    Idempotent: safe to call once at import time. Never registers /metrics
    automatically with PrometheusMetrics — we register our own bearer-token
    protected version below.
    """
    # path=None disables auto /metrics registration; we mount our own.
    PrometheusMetrics(
        app,
        path=None,
        defaults_prefix="signal_scout_http",
        # Group status by class (2xx / 3xx / 4xx / 5xx) to limit cardinality.
        group_by="endpoint",
    )

    # Bearer-protected /metrics
    app.add_url_rule(
        "/metrics", "metrics", _build_metrics_view(token_env_var), methods=["GET"]
    )

    # Lightweight liveness probe. Intentionally cheap — does NOT touch the DB.
    # If you want a readiness probe that *does* touch the DB, add /readyz.
    @app.route("/healthz", methods=["GET"])
    def healthz():
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
