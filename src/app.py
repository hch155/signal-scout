from flask import Flask, render_template, request, jsonify, session, make_response, g, redirect
from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from database import db
from models import BaseStation, User
from sqlalchemy import or_
from queries import get_all_stations, find_nearest_stations, haversine, get_band_stats, get_stats, find_coverage_gaps
from config import settings
from observability import (
    init_observability,
    csrf_failures_total,
    login_failures_total,
    rate_limit_hits_total,
    station_search_total,
    empty_result_total,
    provider_filter_used_total,
    band_filter_used_total,
    requests_by_user_agent_class_total,
    classify_user_agent,
    # PR #44: industry-standard observability extensions
    in_flight_requests,
    http_requests_total,
    http_request_duration_seconds,
    user_action_total,
    request_user_class,
    public_requests_total,
    record_incident,
    compute_public_status,
)
from api_access import (
    require_api_access,
    ensure_user_api_columns,
    generate_api_key,
    is_honeypot,
    record_honeypot_hit,
    seed_honeypot_rows,
)
from api_docs import init_api_docs
from oauth import init_oauth, login_with_provider, callback_for_provider
from dotenv import load_dotenv
from datetime import timedelta, datetime
import markdown, os, random, re, logging, secrets

load_dotenv()

app = Flask(__name__)
# Cloud Run terminates TLS at the edge and forwards to the container over
# HTTP. Without ProxyFix, request.scheme is "http" and url_for(_external=True)
# emits http:// URLs — breaks OAuth redirect_uri matching against the
# https:// URLs registered with Google/GitHub. x_proto=1 trusts the single
# X-Forwarded-Proto hop Cloud Run sets; x_host=1 honors X-Forwarded-Host so
# the canonical hostname (signal-scout.com once domain mapping lands) is
# used in generated URLs.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config['SECRET_KEY'] = settings.secret_key
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = settings.static_max_age
# Cap request body at 1 MiB. Every public endpoint takes small JSON
# (lat/lng, email/password, short names) — without this Flask defaults
# to unlimited and a few concurrent multi-hundred-MiB POSTs can OOM a
# Cloud Run instance. Larger bodies → 413 Request Entity Too Large.
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024
bcrypt = Bcrypt(app)
logging.basicConfig(level=logging.INFO)

# Database configuration

basedir = os.path.abspath(os.path.dirname(__file__))
stations_db_path = settings.stations_db_path or os.path.join(basedir, 'instance', 'stations.db')
users_db_path = settings.users_db_path or os.path.join(basedir, 'instance', 'users.db')

# Persistence seed: when USERS_DB_PATH points to an external mount (e.g.
# Cloud Run gcsfuse volume) and the file isn't there yet, seed it from the
# image-baked copy. Preserves any users that existed when the file was
# committed; on subsequent boots, the mount already has the live data and
# this is a no-op. Without this step, the first boot of a fresh mount would
# create_all() into an empty file → existing users wiped.
import shutil
_baked_users_db = os.path.join(basedir, 'instance', 'users.db')
if (settings.users_db_path
        and settings.users_db_path != _baked_users_db
        and not os.path.exists(settings.users_db_path)
        and os.path.exists(_baked_users_db)):
    os.makedirs(os.path.dirname(settings.users_db_path), exist_ok=True)
    shutil.copy2(_baked_users_db, settings.users_db_path)
    logging.getLogger(__name__).info(
        "Seeded users.db from image into persistent mount: %s", settings.users_db_path
    )

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{stations_db_path}'
app.config['SQLALCHEMY_BINDS'] = {
    'users': f'sqlite:///{users_db_path}'
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Audit fix M-NEW-1 (2026-04-27, partial — short-term mitigation):
# SQLite's default Python-side busy timeout is 5 s. Combined with
# gcsfuse fsync latency on Cloud Run (50–200 ms per COMMIT) and up
# to 4 concurrent gunicorn workers (max-instances=2 × workers=2)
# writing the same file, bursts can serialise long enough to exceed
# the default and surface as `OperationalError: database is locked`
# 500s. Bumping to 30 s lets SQLite retry inside its busy window
# instead of returning the error to the user. The Long-term fix
# (M-NEW-1.b in critique doc) is migrating users.db to Cloud SQL
# Postgres — separate roadmap item, multi-day project.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'timeout': 30},
}
app.config['SQLALCHEMY_BINDS_ENGINE_OPTIONS'] = {
    'users': {'connect_args': {'timeout': 30}},
}
db.init_app(app)
with app.app_context():
    db.create_all()
# Add api_key / api_tier columns to existing prod users.db (no-op on fresh DB).
# When the app grows to multiple DB engines this gets replaced by Alembic.
ensure_user_api_columns(app, db)
# Audit fix L-NEW-4 (2026-04-27): plant honeypot rows in BaseStation
# so prefix-search scrapers surface them. No-op when HONEYPOT_BTS_IDS
# env is unset.
try:
    _seeded = seed_honeypot_rows(app, db)
    if _seeded:
        app.logger.info("Seeded %d honeypot BTS rows", _seeded)
except Exception:
    app.logger.exception("seed_honeypot_rows raised — continuing boot")

# HTTPS encryption for Flask


# Session configuration — Flask's *default* signed-cookie session
# (itsdangerous-backed). Stateless: session payload lives in the cookie
# itself, no server-side store. Critical for Cloud Run multi-instance:
# previous Flask-Session filesystem storage put session per-instance and
# requests bouncing between instances broke CSRF (cookie X on instance A,
# absent on instance B → 403). Signed cookies sidestep this entirely.
# Session payload is tiny (~150 bytes: _csrf_token + user_id + user_location)
# — well below the ~4KB cookie limit.
app.permanent_session_lifetime = timedelta(days=7)
app.config["SESSION_COOKIE_SAMESITE"] = 'Lax'
# Secure cookie only over HTTPS in production. On http://localhost the
# Secure flag drops the cookie entirely, which would block CSRF flow during
# local dev / perf tests. Production env sets ENV=PRODUCTION (cd.yaml).
app.config["SESSION_COOKIE_SECURE"] = settings.cookie_secure
app.config["SESSION_COOKIE_HTTPONLY"] = True
# Make every session permanent so PERMANENT_SESSION_LIFETIME applies (default
# would expire on browser close). Done via before_request so it stays one place.
@app.before_request
def _make_session_permanent():
    session.permanent = True

limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["16 per minute"])

# PL geographic bounds for input validation. Strict PL would be
# 49.0–55.5°N / 14.0–24.2°E — but the dataset includes some maritime
# stations in the Polish EEZ (latarnie, offshore wind), and a user
# clicking just over the German / Czech / Belarussian / Lithuanian
# border by 1-2 km shouldn't get a curt 400. ±0.05° (~5 km) buffer.
PL_LAT_MIN, PL_LAT_MAX = 48.95, 55.55
PL_LNG_MIN, PL_LNG_MAX = 13.95, 24.25


def _coords_in_bounds(lat: float, lng: float) -> bool:
    return PL_LAT_MIN <= lat <= PL_LAT_MAX and PL_LNG_MIN <= lng <= PL_LNG_MAX

# Wire Prometheus exporter (/metrics with bearer-token auth) and /healthz.
init_observability(app)

# OpenAPI / Swagger UI on /api/v1/docs/, spec on /api/v1/openapi.json.
init_api_docs(app)
init_oauth(app)


# PR #48.7: OAuth sign-in routes. Each provider gates itself on
# settings.<provider>_oauth_client_id — empty → 404 + button hidden
# in /login. So flipping a provider on/off is a Cloud Run env update,
# no code change.
@app.route('/auth/google/login')
@limiter.limit("10 per minute")
def oauth_google_login():
    return login_with_provider('google')


@app.route('/auth/google/callback')
def oauth_google_callback():
    return callback_for_provider('google')


@app.route('/auth/github/login')
@limiter.limit("10 per minute")
def oauth_github_login():
    return login_with_provider('github')


@app.route('/auth/github/callback')
def oauth_github_callback():
    return callback_for_provider('github')


@app.route('/auth/facebook/login')
@limiter.limit("10 per minute")
def oauth_facebook_login():
    return login_with_provider('facebook')


@app.route('/auth/facebook/callback')
def oauth_facebook_callback():
    return callback_for_provider('facebook')


@app.route('/auth/2fa_challenge', methods=['GET'])
def oauth_2fa_challenge():
    """Browser-side TOTP prompt for users who completed OAuth identity
    verification but still owe us a 2FA code. The OAuth callback parks
    them in `pending_2fa_user_id`; this page POSTs to /login/totp via
    JS and on success lets the user reach /account.

    Inline HTML on purpose — keeps the 2FA gate self-contained, no
    template/theme dependency, and the page only ships when the user
    is mid-flow (1-2 sec window per sign-in)."""
    if 'pending_2fa_user_id' not in session:
        return redirect('/?oauth_error=no_pending_2fa')
    csrf = session.get('_csrf_token') or ''
    body = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><title>Two-factor code required - Signal-Scout</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:32px;max-width:380px;width:100%;box-shadow:0 10px 40px rgba(0,0,0,.3)}
h1{font-size:20px;margin:0 0 8px;color:#f1f5f9}
p{color:#94a3b8;margin:0 0 20px;font-size:14px;line-height:1.5}
input[name=code]{width:100%;background:#0f172a;border:1px solid #475569;color:#f1f5f9;padding:12px;border-radius:8px;font-size:18px;letter-spacing:4px;text-align:center;font-family:monospace;box-sizing:border-box}
input[name=code]:focus{outline:none;border-color:#3b82f6}
button{margin-top:16px;width:100%;background:#3b82f6;color:#fff;padding:12px;border-radius:8px;border:none;font-weight:600;font-size:14px;cursor:pointer}
button:hover{background:#2563eb}
button:disabled{opacity:.6;cursor:not-allowed}
.err{margin-top:12px;color:#fca5a5;font-size:13px;min-height:1.2em}
.note{margin-top:12px;color:#64748b;font-size:12px}
.note a{color:#94a3b8}
</style>
</head><body>
<div class="card">
<h1>Two-factor code required</h1>
<p>You signed in with a provider. Enter the 6-digit code from your
authenticator app to finish.</p>
<form id="f" autocomplete="off">
<input name="code" autofocus required pattern="[0-9 ]{6,12}" inputmode="numeric"
       placeholder="123456" autocomplete="one-time-code">
<button type="submit" id="b">Verify and continue</button>
<div class="err" id="e"></div>
<p class="note">Lost the device? Use a recovery code in the same field.
Or <a href="/?cancel=1">cancel sign-in</a>.</p>
</form>
</div>
<script>
const csrfToken = """ + ('"' + csrf + '"') + """;
const f=document.getElementById('f'),b=document.getElementById('b'),e=document.getElementById('e');
f.addEventListener('submit',async ev=>{
  ev.preventDefault();
  e.textContent='';b.disabled=true;b.textContent='Checking...';
  const code=f.code.value.trim();
  try{
    const r=await fetch('/login/totp',{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},
      body:JSON.stringify({code})});
    const j=await r.json().catch(()=>({}));
    if(r.ok && j.success){ window.location='/account'; return; }
    e.textContent=j.error || j.message || 'Wrong code, try again.';
  }catch(err){ e.textContent='Network error - try again.'; }
  b.disabled=false;b.textContent='Verify and continue';
});
</script>
</body></html>"""
    response = make_response(body)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.errorhandler(429)
def rate_limit_exceeded(e):
    rate_limit_hits_total.labels(endpoint=request.endpoint or "unknown").inc()
    return '<html><body><h1>Rate Limit Exceeded</h1><p>Please wait a minute before making new requests.</p><img src="/static/limitexceededfresh.png" alt="Rate Limit Exceeded"></body></html>', 429

def _build_csp_policy() -> str:
    """CSP composed at startup so the Plausible host (env-driven) is allowed
    in script-src + connect-src only when configured. Keeps the CSP strict
    by default and avoids opening allowances no one is using."""
    plausible_url = settings.plausible_script_url.strip()
    plausible_origin = ''
    if plausible_url:
        # Trim path/query to leave just scheme+host for CSP.
        from urllib.parse import urlparse
        parsed = urlparse(plausible_url)
        if parsed.scheme and parsed.netloc:
            plausible_origin = f"{parsed.scheme}://{parsed.netloc}"

    script_extras = ' ' + plausible_origin if plausible_origin else ''
    connect_extras = ' ' + plausible_origin if plausible_origin else ''

    return (
        "default-src 'self'; "
        f"script-src 'self'{script_extras}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: "
        "https://*.tile.openstreetmap.org https://tiles.stadiamaps.com "
        "https://*.basemaps.cartocdn.com "
        "https://server.arcgisonline.com; "
        "font-src 'self' data:; "
        f"connect-src 'self'{connect_extras}; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "object-src 'none'"
    )


CSP_POLICY = _build_csp_policy()

PERMISSIONS_POLICY = (
    "geolocation=(self), camera=(), microphone=(), payment=(), "
    "usb=(), magnetometer=(self), gyroscope=(self), accelerometer=(self)"
)

# /embed/* widget needs geolocation permitted to ANY embedding origin so
# cross-site iframes can prompt the user. Camera/mic/payment stay denied.
EMBED_PERMISSIONS_POLICY = (
    "geolocation=*, camera=(), microphone=(), payment=(), "
    "usb=(), magnetometer=(self), gyroscope=(self), accelerometer=(self)"
)


@app.after_request
def _record_user_agent_class(response):
    # Skip /metrics + /healthz + /status so probes don't dominate the
    # bucket counts.
    if request.path in ('/metrics', '/healthz', '/status'):
        return response
    requests_by_user_agent_class_total.labels(
        ua_class=classify_user_agent(request.headers.get('User-Agent'))
    ).inc()
    return response


# ── PR #44: USE-method saturation + RED-method per-tier hooks ───────────────
#
# `in_flight_requests` is a Gauge incremented on every request entry and
# decremented on every request exit (including exceptions), giving a
# saturation read at any instant. `public_requests_total` keeps a count
# of every customer-visible request — surfaced unfiltered on the public
# /status page. `record_incident()` stamps the wall-clock time of the
# most-recent 5xx so /status can render "Last incident: …".

_INFRA_PATHS = ('/metrics', '/healthz', '/status')


@app.before_request
def _saturation_inc():
    if request.path in _INFRA_PATHS:
        return
    try:
        in_flight_requests.inc()
    except Exception:
        pass
    # Per-endpoint duration (added 2026-04-28). Stamp request start
    # so the after_request hook can compute elapsed without needing
    # its own clock reading. Stored on flask.g so concurrent requests
    # don't trample each other.
    try:
        from flask import g as _g
        import time as _t
        _g._req_start_perf = _t.perf_counter()
    except Exception:
        pass


@app.after_request
def _saturation_dec_and_count(response):
    if request.path in _INFRA_PATHS:
        return response
    try:
        in_flight_requests.dec()
        public_requests_total.inc()
        if 500 <= response.status_code < 600:
            record_incident()
    except Exception:
        pass
    # Per-endpoint HTTP funnel + duration (added 2026-04-28).
    # endpoint label uses request.endpoint (the Flask view-function
    # name) rather than request.path so dynamic routes like
    # /account/keys/<int:key_id>/revoke don't blow up cardinality
    # with one series per key_id. Status bucketed to 2xx/3xx/4xx/5xx
    # for the same reason — 410 vs 404 vs 403 etc. all roll into 4xx.
    try:
        endpoint = request.endpoint or 'unknown'
        status_bucket = f"{response.status_code // 100}xx"
        user_class = request_user_class()
        http_requests_total.labels(
            method=request.method,
            endpoint=endpoint,
            status=status_bucket,
            user_class=user_class,
        ).inc()
        from flask import g as _g
        import time as _t
        start = getattr(_g, '_req_start_perf', None)
        if start is not None:
            http_request_duration_seconds.labels(
                method=request.method,
                endpoint=endpoint,
            ).observe(_t.perf_counter() - start)
    except Exception:
        pass
    return response


@app.teardown_request
def _saturation_safety_dec(exc):
    """If an exception escaped the after_request chain (e.g. WSGI-level
    abort), make sure the gauge doesn't leak upward forever."""
    if request.path in _INFRA_PATHS:
        return
    if exc is not None:
        try:
            in_flight_requests.dec()
            record_incident()
        except Exception:
            pass


def _csp_for_path(path: str) -> str:
    """CSP varies per route family. /embed/* relaxes frame-ancestors so
    allowed origins can iframe the widget; /api/v1/docs/ (Swagger UI) needs
    'unsafe-inline' in script-src because flasgger renders an inline
    <script>window.onload = ...</script> block to bootstrap the UI —
    without that the page hangs on LOADING forever. Swagger also loads
    Google Fonts CSS which needs the fonts.googleapis.com origin in
    style-src + font-src.
    Everything else stays locked."""
    if path.startswith('/embed/') and settings.embed_allowed_origins:
        ancestors = ' '.join(settings.embed_allowed_origins)
        return CSP_POLICY.replace("frame-ancestors 'none'",
                                  f"frame-ancestors {ancestors}")
    if path.startswith('/api/v1/docs') or path.startswith('/api/v1/flasgger_static'):
        policy = CSP_POLICY
        # Permit the inline Swagger bootstrap script.
        policy = policy.replace(
            "script-src 'self'",
            "script-src 'self' 'unsafe-inline'",
        )
        # Allow Google Fonts CSS + font files used by Swagger UI.
        policy = policy.replace(
            "style-src 'self' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        )
        policy = policy.replace(
            "font-src 'self' data:",
            "font-src 'self' data: https://fonts.gstatic.com",
        )
        return policy
    return CSP_POLICY


@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Audit fix (Low — headers): X-XSS-Protection is deprecated. Modern
    # Chromium/Firefox/Safari ignore it; older browsers' implementation
    # had documented XSS-amplifying corner cases. Removed in favor of
    # the strict CSP set further down (which is the actual modern XSS
    # defence). Kept HSTS extended preload-eligible (>=1 year, includes
    # subdomains, preload directive).
    response.headers['Strict-Transport-Security'] = (
        'max-age=63072000; includeSubDomains; preload'
    )
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = (
        EMBED_PERMISSIONS_POLICY
        if request.path.startswith('/embed/')
        else PERMISSIONS_POLICY
    )
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = _csp_for_path(request.path)
    # X-Frame-Options is the legacy sibling of frame-ancestors. For /embed/*
    # we drop it entirely so allowed origins can frame; modern browsers
    # honor frame-ancestors over XFO when both are present, but old browsers
    # see XFO=DENY first and refuse — so it must go.
    if not request.path.startswith('/embed/') or not settings.embed_allowed_origins:
        response.headers['X-Frame-Options'] = 'DENY'
    # Authenticated pages must not be cached: after logout the browser would
    # otherwise serve the rendered HTML (with email + API key) from BFCache /
    # disk cache on Back-button or direct URL re-entry, even though the
    # server-side session is gone. no-store + Vary: Cookie kills both BFCache
    # and intermediary caches for any response that depended on session state.
    if 'user_id' in session or request.path.startswith('/account'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        existing_vary = response.headers.get('Vary', '')
        if 'Cookie' not in existing_vary:
            response.headers['Vary'] = (existing_vary + ', Cookie').lstrip(', ')
    return response

# PR #48: positive caching for read-only public pages. /data and /tips
# render markdown (mostly static — content edits ship via deploy); /stats
# renders aggregated SQL counts that change at most once a month with the
# UKE refresh. Without these headers every page-load eats a full Flask
# render + DB hit; with ETag + 304 a CDN / browser short-circuits to a
# 0-byte 304 on revisits.
_PUBLIC_CACHE_PATHS = {'/data', '/stats', '/tips', '/tips/content', '/privacy'}
# 5 min fresh + 10 min stale-while-revalidate. Long enough that a user
# clicking around the site re-uses the cache; short enough that a content
# edit (markdown push) reaches users within minutes after deploy.
_PUBLIC_CACHE_MAX_AGE = 300
_PUBLIC_CACHE_SWR     = 600
# /tips serves different content for logged-in vs anonymous users
# (tips_registered.md vs tips.md). Without Vary:Cookie an intermediary
# cache could serve the registered version to a logged-out user.
_COOKIE_VARYING_CACHE_PATHS = {'/tips', '/tips/content'}


def _set_content_etag(response, content_key: str) -> None:
    """Set a strong ETag derived from a stable content key.

    Hashing the rendered response body is a trap: every page on this
    site embeds a per-session CSRF meta tag from `base.html`, so
    body-based ETags change on every request and 304 short-circuits
    never fire. The fix is to hash a key that captures only the
    content the cache should be sensitive to (markdown mtime, dataset
    version, etc.) plus the deploy SHA so a new build invalidates
    everyone's cache automatically.
    """
    import hashlib as _h
    digest = _h.sha256(
        f"{content_key}|{settings.app_version}".encode('utf-8')
    ).hexdigest()
    response.set_etag(digest)


@app.after_request
def set_public_cache_headers(response):
    """Cache-Control + If-None-Match for read-only public pages.

    Runs after `set_security_headers`, which already sets
    `Cache-Control: no-store` on authenticated / `/account/*` responses.
    We refuse to overwrite an existing Cache-Control so that no-store
    always wins when present.

    The view function is responsible for setting a content-derived
    ETag via `_set_content_etag()` — body-hashing here would be wrong
    because every page embeds per-session CSRF tokens.
    """
    if request.path not in _PUBLIC_CACHE_PATHS:
        return response
    if response.status_code != 200:
        return response
    if response.headers.get('Cache-Control'):
        return response
    # Only act when the view set an ETag — otherwise we have no
    # stable cache key and can't honour conditional requests.
    if not response.headers.get('ETag'):
        return response
    response.make_conditional(request)
    response.headers['Cache-Control'] = (
        f'public, max-age={_PUBLIC_CACHE_MAX_AGE}, '
        f'stale-while-revalidate={_PUBLIC_CACHE_SWR}'
    )
    if request.path in _COOKIE_VARYING_CACHE_PATHS:
        existing_vary = response.headers.get('Vary', '')
        if 'Cookie' not in existing_vary:
            response.headers['Vary'] = (existing_vary + ', Cookie').lstrip(', ')
    return response


def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token

# Plausible Analytics — script + domain set via env. Both must be present
# to render the tracker; either missing → tracker silently disabled.
app.jinja_env.globals['plausible_script_url'] = settings.plausible_script_url
app.jinja_env.globals['plausible_domain'] = settings.plausible_domain
app.jinja_env.globals['canonical_origin'] = settings.canonical_origin
# PR #46.5: footer-rendered build version. cd.yaml builds APP_VERSION as
# 'YYYY.MM.DD-<sha7>' (CalVer + git SHA — Stripe-style date versioning,
# no SemVer bookkeeping). Local dev → "dev". Owner clicks the footer link
# to land on the deployed commit on GitHub — instant "what's actually
# running right now" verification, was a recurring uncertainty during
# the sprint.
app.jinja_env.globals['app_version'] = settings.app_version
app.jinja_env.globals['app_version_sha'] = settings.app_version_sha
app.jinja_env.globals['repo_url'] = settings.repo_url
# PR #48.7: OAuth provider gating in base.html. Buttons hidden when
# the corresponding client_id env var is empty.
app.jinja_env.globals['google_oauth_enabled'] = bool(settings.google_oauth_client_id)
app.jinja_env.globals['github_oauth_enabled'] = bool(settings.github_oauth_client_id)
app.jinja_env.globals['facebook_oauth_enabled'] = bool(settings.facebook_oauth_client_id)

def validate_csrf():
    # Audit fix (High — timing leak): use hmac.compare_digest instead
    # of `!=`. Plain string equality short-circuits on the first
    # mismatched byte; an attacker measuring response time can
    # progressively guess the token byte-by-byte. compare_digest is
    # constant-time (and accepts both str and bytes).
    import hmac as _hmac
    token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
    expected = session.get('_csrf_token')
    if not token or not expected:
        return False
    return _hmac.compare_digest(str(token), str(expected))

SLOGANS = [
    ("On the Move?", "Navigate to the Nearest Base Stations for Uninterrupted Connectivity!"),
    ("Seeking Signal?", "Discover the Closest Connectivity Points for Seamless Communication!"),
    ("Chasing Coverage?", "Pinpoint the Best Signal Sources for Flawless Connections!"),
    ("Stay Connected Everywhere", "Discover the Closest Base Stations for Optimal Signal Strength!"),
    ("Dropping Calls?", "Catch the color for quality coverage!"),
    ("Found Getaway?", "Secure your signal!")
]

@app.route('/')
def home():
    slogan_title, slogan_text = random.choice(SLOGANS)
    # PR #48.2: don't ship Leaflet + map JS to bots / CLIs. Crawlers
    # were burning through the Stadia tile free tier (200k/mo) and
    # contribute zero SEO value from the rendered map. Real browsers
    # (browser_chrome / browser_firefox / browser_safari / browser_other
    # / unknown) still get the full app. Headless renderers that lie
    # about their UA slip through; that's fine — most spend isn't from
    # them.
    ua_class = classify_user_agent(request.headers.get('User-Agent'))
    is_bot = ua_class.endswith('bot') or ua_class == 'cli'
    return render_template(
        'map.html',
        slogan_title=slogan_title,
        slogan_text=slogan_text,
        is_bot=is_bot,
    )

# PR #27: per-file (path, mtime) → rendered-html cache. /data, /tips,
# /stats render markdown on every request — perf logs showed it
# dominates p95 (~150ms). Markdown content lives in committed files that
# only change at deploy time, so a process-local cache keyed by mtime
# auto-invalidates without manual flush. Bounded implicitly by the small
# number of .md files in src/content/.
_MARKDOWN_HTML_CACHE: dict[str, tuple[float, str]] = {}


def get_html_content_from_markdown(file_name):
    file_path = os.path.join(basedir, 'content', file_name)
    try:
        mtime = os.path.getmtime(file_path)
    except OSError:
        mtime = 0.0
    cached = _MARKDOWN_HTML_CACHE.get(file_path)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(file_path, 'r') as file:
        markdown_content = file.read()
    html_content = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])
    _MARKDOWN_HTML_CACHE[file_path] = (mtime, html_content)
    return html_content

def _md_etag_key(file_name: str) -> str:
    """Cache key for a markdown page: file path + mtime."""
    file_path = os.path.join(basedir, 'content', file_name)
    try:
        return f"{file_name}:{os.path.getmtime(file_path):.6f}"
    except OSError:
        return f"{file_name}:0"


@app.route('/data')
def data_page():
    html_content = get_html_content_from_markdown('data.md')
    response = make_response(render_template('data.html', content=html_content))
    _set_content_etag(response, _md_etag_key('data.md'))
    return response

@app.route('/stats')
def stats_page():
    stats = get_stats()
    # Stations DB only changes with the monthly UKE refresh — its mtime
    # is the right cache key for /stats. Falls back to app_version if
    # the file is missing (test envs / first boot) so the ETag still
    # invalidates per deploy.
    try:
        db_mtime = os.path.getmtime(stations_db_path)
        from datetime import datetime as _dt
        last_refresh_iso = _dt.utcfromtimestamp(db_mtime).strftime('%Y-%m-%d')
    except OSError:
        db_mtime = 0.0
        last_refresh_iso = 'unknown'
    response = make_response(render_template(
        'stats.html', stats=stats, last_refresh=last_refresh_iso,
    ))
    _set_content_etag(response, f"stats:{db_mtime:.6f}")
    return response

@app.route('/tips')
def tips_page():
    file_name = 'tips_registered.md' if 'user_id' in session else 'tips.md'
    html_content = get_html_content_from_markdown(file_name)
    response = make_response(render_template('tips.html', content=html_content))
    _set_content_etag(response, _md_etag_key(file_name))
    return response

@app.route('/tips/content')
def tips_content():
    file_name = 'tips_registered.md' if 'user_id' in session else 'tips.md'
    html_content = get_html_content_from_markdown(file_name)
    response = make_response(html_content)
    _set_content_etag(response, _md_etag_key(file_name))
    return response

@app.route('/privacy')
def privacy_page():
    """GDPR Art. 13 transparency notice. Markdown-rendered like /data
    and /tips so updates ship via deploy + content edits, not template
    changes. Cached publicly via the same _set_content_etag path."""
    html_content = get_html_content_from_markdown('privacy.md')
    response = make_response(render_template('privacy.html', content=html_content))
    _set_content_etag(response, _md_etag_key('privacy.md'))
    return response


@app.route('/data-deletion')
def data_deletion_page():
    """User data deletion instructions, required by Facebook OAuth app
    config (User data deletion field) and a useful standalone page for
    GDPR Art. 17 (right to erasure). Plain inline HTML so FB's URL
    validator can scrape it without theme/template noise."""
    body = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><title>Delete your Signal-Scout data</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:system-ui,-apple-system,sans-serif;max-width:640px;margin:2rem auto;padding:0 1rem;line-height:1.55;color:#222}h1{font-size:1.4rem}code{background:#f4f4f4;padding:.1rem .3rem;border-radius:3px}a{color:#2563eb}</style>
</head><body>
<h1>Delete your Signal-Scout data</h1>
<p>You can delete your account and all associated data at any time:</p>
<ol>
  <li>Sign in at <a href="https://signal-scout.com/">signal-scout.com</a>.</li>
  <li>Open <a href="https://signal-scout.com/account">/account</a>.</li>
  <li>Use <strong>Delete my account</strong>. The action is irreversible
      and removes your email, password hash, API keys, location history,
      and login events within 24 hours.</li>
</ol>
<p>If you signed in with Google, GitHub, or Facebook, deleting your
account in Signal-Scout removes our copy of the email mapping; revoke
the app at the provider to also stop them from sending us tokens
(<a href="https://myaccount.google.com/permissions">Google</a>,
<a href="https://github.com/settings/applications">GitHub</a>,
<a href="https://www.facebook.com/settings?tab=applications">Facebook</a>).</p>
<p>If you cannot sign in (lost access), email
<a href="mailto:hello@signal-scout.com">hello@signal-scout.com</a>
from the address tied to the account and we will delete it manually.</p>
<p>See our <a href="/privacy">privacy notice</a> for the full GDPR
Art. 13 disclosure.</p>
</body></html>"""
    response = make_response(body)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

# PR #48.3: signed-token email unsubscribe.
#
# GET  /unsubscribe/<token> renders a confirm page (do NOT flip on GET
# because email clients prefetch links for malware scanning — Outlook,
# Gmail "show images" etc. would silently opt the user out).
#
# POST /unsubscribe/<token> validates the token, flips
# email_alerts_enabled = False on the user, redirects to a "you're
# unsubscribed, change your mind anytime in /account" confirmation.
#
# Tokens have no expiry — the unsubscribe link in a 6-month-old email
# should still work without forcing the user to log in.
def _decode_unsubscribe_token(token: str):
    from itsdangerous import URLSafeSerializer, BadSignature
    serializer = URLSafeSerializer(settings.secret_key, salt='email-unsubscribe')
    try:
        return int(serializer.loads(token))
    except (BadSignature, ValueError, TypeError):
        return None


@app.route('/unsubscribe/<token>', methods=['GET'])
def unsubscribe_email(token):
    user_id = _decode_unsubscribe_token(token)
    from models import User as _U
    user = _U.query.get(user_id) if user_id else None
    return render_template(
        'unsubscribe.html',
        token=token,
        user=user,
        already_unsubscribed=bool(user and not user.email_alerts_enabled),
    )


@app.route('/unsubscribe/<token>', methods=['POST'])
@limiter.limit("10 per hour")
def unsubscribe_email_confirm(token):
    user_id = _decode_unsubscribe_token(token)
    if not user_id:
        return render_template('unsubscribe.html', token=token,
                               user=None, error='invalid_token'), 400
    from models import User as _U
    from database import db as _db
    user = _U.query.get(user_id)
    if not user:
        return render_template('unsubscribe.html', token=token,
                               user=None, error='user_not_found'), 404
    user.email_alerts_enabled = False
    try:
        _db.session.commit()
    except Exception:
        _db.session.rollback()
        return render_template('unsubscribe.html', token=token, user=user,
                               error='db_error'), 500
    return render_template('unsubscribe.html', token=token, user=user,
                           done=True)


@app.route('/account/email_preference', methods=['POST'])
@limiter.limit("20 per hour")
def update_email_preference():
    """Toggle email_alerts_enabled from the /account UI. Body:
    {enabled: true|false}. CSRF + session protected."""
    if not validate_csrf():
        return jsonify({"error": "csrf_failed"}), 403
    if 'user_id' not in session:
        return jsonify({"error": "auth_required"}), 401
    from models import User as _U
    from database import db as _db
    user = _U.query.get(session['user_id'])
    if not user:
        return jsonify({"error": "user_not_found"}), 404
    payload = request.get_json(silent=True) or {}
    user.email_alerts_enabled = bool(payload.get('enabled', True))
    try:
        _db.session.commit()
    except Exception:
        _db.session.rollback()
        return jsonify({"error": "db_error"}), 500
    return jsonify({"success": True,
                    "email_alerts_enabled": user.email_alerts_enabled})


# PR #48.4: admin-only stats endpoint backed by SubmitLocationEvent.
# Bare-bones JSON for now — surfaces aggregates so the owner can see
# usage shape (top spots, browser breakdown, hourly distribution,
# in-PL vs out-of-PL ratio, anon vs logged-in). UI on top of this is
# a future iteration; for now the JSON is enough to make decisions.
def _is_admin(user) -> bool:
    if not user or not user.email:
        return False
    return user.email.lower() in settings.admin_emails or user.role == 'admin'


@app.route('/admin/run_retention', methods=['POST'])
@limiter.limit("12 per hour")
def admin_run_retention():
    """Audit fix L-NEW-1 (2026-04-27): explicit retention trigger
    suitable for Cloud Scheduler. Auth: admin OR
    `Authorization: Bearer <METRICS_BEARER_TOKEN>` so a Cloud
    Scheduler HTTP target can call without going through a user
    session. Idempotent. Returns {success, deleted}.
    """
    auth_header = request.headers.get('Authorization', '')
    bearer_ok = bool(
        settings.metrics_bearer_token
        and auth_header == f"Bearer {settings.metrics_bearer_token}"
    )
    if not bearer_ok:
        if 'user_id' not in session:
            return jsonify({"error": "auth_required"}), 401
        from models import User as _U
        user = _U.query.get(session['user_id'])
        if not _is_admin(user):
            return jsonify({"error": "forbidden"}), 403
        if not validate_csrf():
            return jsonify({"error": "csrf_failed"}), 403

    from api_access import purge_submit_location_events_older_than_30_days
    engine = db.get_engine(app, bind='users')
    try:
        deleted = purge_submit_location_events_older_than_30_days(engine)
    except Exception:
        app.logger.exception("admin_run_retention failed")
        return jsonify({"error": "retention_failed"}), 500
    app.logger.info("Retention sweep deleted %d SubmitLocationEvent rows", deleted)
    return jsonify({"success": True, "deleted": deleted}), 200


@app.route('/admin/stats', methods=['GET'])
@limiter.limit("30 per hour")
def admin_stats():
    if 'user_id' not in session:
        return jsonify({"error": "auth_required"}), 401
    from models import User as _U, SubmitLocationEvent as _SLE
    user = _U.query.get(session['user_id'])
    if not _is_admin(user):
        return jsonify({"error": "forbidden", "message": "Admin only."}), 403

    # 24h-window aggregates by default; ?days=N to widen.
    try:
        days = max(1, min(30, int(request.args.get('days', '1'))))
    except (TypeError, ValueError):
        days = 1
    from sqlalchemy import func as _f
    cutoff = datetime.utcnow() - timedelta(days=days)

    base_q = _SLE.query.filter(_SLE.created_at >= cutoff)
    total = base_q.count()
    in_pl_count = base_q.filter(_SLE.in_pl.is_(True)).count()
    out_pl_count = total - in_pl_count
    logged_in_count = base_q.filter(_SLE.user_id.isnot(None)).count()
    anon_count = total - logged_in_count

    # Top 10 (lat_bucket, lng_bucket) by hit count — coarse heatmap.
    top_spots = (
        db.session.query(
            _SLE.lat_bucket, _SLE.lng_bucket,
            _f.count('*').label('hits'),
        )
        .filter(_SLE.created_at >= cutoff)
        .group_by(_SLE.lat_bucket, _SLE.lng_bucket)
        .order_by(_f.count('*').desc())
        .limit(10)
        .all()
    )

    browser_counts = dict(
        db.session.query(
            _SLE.browser_class, _f.count('*'),
        )
        .filter(_SLE.created_at >= cutoff)
        .group_by(_SLE.browser_class)
        .all()
    )

    payload = {
        "window_days": days,
        "total_events": total,
        "in_pl": in_pl_count,
        "out_of_pl": out_pl_count,
        "logged_in": logged_in_count,
        "anonymous": anon_count,
        "top_spots": [
            {"lat": float(lat), "lng": float(lng), "hits": int(hits)}
            for (lat, lng, hits) in top_spots
        ],
        "browsers": {k: int(v) for k, v in browser_counts.items()},
    }
    # PR #48.6: HTML by default for browser visits, JSON on
    # ?format=json. Browser visit hits the rendered page directly;
    # programmatic clients (scripts, dashboards) opt-in to JSON.
    if request.args.get('format') == 'json':
        return jsonify(payload)
    return render_template('admin_stats.html', data=payload)


@app.route('/account/test_email', methods=['POST'])
@limiter.limit("3 per hour")
def test_email_endpoint():
    """PR #48 SendGrid smoke test: triggers a single transactional email
    through the active backend (settings.email_backend) to the logged-in
    user's own email address. Rate-limited to 3/hour to prevent misuse;
    requires CSRF + active session.

    Audit fix M-NEW-5 (2026-04-27): admin-gated. The endpoint exists
    only as an operator smoke test for SendGrid configuration changes.
    Combined with the in-memory rate limiter (per-instance, not per-
    cluster) and 2 Cloud Run instances, the prior 3/hour was 6/hour
    per IP and a fleet of disposable accounts could burn the SendGrid
    quota at the operator's expense. Admin-only closes that vector
    completely while keeping the smoke-test capability for ops.

    Returns: {success, backend, to} on success or {error, message} on
    failure. Reuses the password_changed template — content doesn't
    matter for the smoke test, what matters is the SendGrid API call
    going through (visible in SendGrid Activity Feed)."""
    if not validate_csrf():
        return jsonify({"error": "csrf_failed",
                        "message": "Missing or invalid X-CSRF-Token"}), 403
    if 'user_id' not in session:
        return jsonify({"error": "auth_required",
                        "message": "Login required."}), 401
    from models import User as _U
    from emails import send_password_changed
    user = _U.query.get(session['user_id'])
    if not user:
        return jsonify({"error": "user_not_found"}), 404
    if not _is_admin(user):
        return jsonify({"error": "forbidden",
                        "message": "Admin only."}), 403
    ok = send_password_changed(user)
    return jsonify({
        "success": bool(ok),
        "backend": settings.email_backend,
        "from": settings.email_from,
        "to": user.email,
    }), (200 if ok else 502)


@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')


# ── PR #44: Customer-facing public status page ──────────────────────────────
#
# Self-contained Plausible-style status page. Backed by the SAME in-process
# Prometheus counters that Grafana pulls — no external Prom round-trip
# (faster, and means the page works even if the NUC is offline).
#
# Privacy boundary (intentional):
#   This route MUST NOT surface anything from the security counters. No
#   CSRF / login-failure / honeypot / API-key / tier breakdown. The page is
#   shown to prospective B2B customers; security signals stay private and
#   live on the operator-only Grafana dashboard.
#
# `compute_public_status()` enforces the boundary in code — it only reads
# availability, latency and the public_requests_total counter. Adding a
# panel here in the future means extending that function (review checks
# the diff against the privacy boundary).

@app.route('/status')
def public_status():
    """Customer-facing service health page (HTML).

    Returns a tiny self-contained page with green/yellow/red component
    indicators, current SLOs, and last-incident timestamp. Pulls its
    numbers from the in-process registry, so Cloud Run min-instances=0
    means a freshly-cold-started instance shows pristine counters
    (technically correct: this instance has had no errors yet).

    Optional ?format=json returns the same payload as machine-readable
    JSON so external uptime checks / status-aggregator pages can consume
    it without scraping HTML.
    """
    payload = compute_public_status()
    if request.args.get('format') == 'json':
        return jsonify(payload), 200
    return render_template('status.html', s=payload), 200


@app.route('/submit_location', methods=['POST'])
@limiter.limit("30 per minute")
def submit_location():
    if not validate_csrf():
        csrf_failures_total.labels(endpoint='submit_location').inc()
        return jsonify({'error': 'Invalid request'}), 403
    try:
        data = request.get_json(silent=True) or {}
        if 'lat' not in data or 'lng' not in data:
            return jsonify({'error': 'Missing coordinates'}), 400
        user_lat = float(data['lat'])
        user_lng = float(data['lng'])

        if not _coords_in_bounds(user_lat, user_lng):
            # Easter egg path. Returns 200 (not 400) so the frontend
            # `globalFetch` doesn't bail into .catch — that was the bug
            # behind the "loading spinner forever" / no easter-egg toast
            # symptom in prod (frontend treated the 400 as a network
            # error, never hit the success branch where the message box
            # is unhidden).
            return jsonify({
                'outside_pl': True,
                'message': (
                    "Sorry, this map only covers Poland. "
                    "Coverage you're missing: ~22,000 base stations, "
                    "4 operators (Orange, Play, Plus, T-Mobile), "
                    "5G / LTE / UMTS / GSM bands."
                ),
                'stats': {
                    'unique_bts': 21858,
                    'operators': 4,
                    'bands': ['5G', 'LTE', 'UMTS', 'GSM'],
                },
                'stations': [],
                'count': 0,
            })

        session['user_location'] = {'lat': user_lat, 'lng': user_lng}
        # PR #29: persist saved location to User row so the snapshot/diff
        # feed in /account/changes has a centre point. Best-effort: a write
        # failure here must NOT break the user-facing /submit_location flow.
        if 'user_id' in session:
            try:
                user = db.session.get(User, session['user_id'])
                if user is not None:
                    user.last_location_lat = user_lat
                    user.last_location_lng = user_lng
                    db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.exception("Could not persist user location")
        # Audit fix (Medium — backend): mirror the bounds enforced on
        # /stations so a body POST can't bypass the documented
        # 0.1–10 km / 1–10 limit caps. find_nearest_stations is
        # cheap-ish but unbounded radius would scan the whole table.
        limit = data.get('limit', 9)
        max_distance = data.get('max_distance', None)
        try:
            if max_distance is not None:
                max_distance = float(max_distance)
                if max_distance < 0.1 or max_distance > 10:
                    return jsonify({"error": "Invalid parameter",
                                    "message": "Max distance must be between 0.1 and 10 km."}), 400
                limit = None
            elif limit is not None:
                limit = int(limit)
                if limit < 1 or limit > 10:
                    return jsonify({"error": "Invalid parameter",
                                    "message": "Limit must be between 1 and 10."}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid parameter",
                            "message": "limit/max_distance must be numeric."}), 400

        station_search_total.labels(endpoint='submit_location').inc()
        # 2026-04-28: business-action counter so Grafana can answer
        # "how many submit_location calls are landing per minute,
        # split between anon and logged-in browsers + API tiers?".
        try:
            user_action_total.labels(
                action='submit_location',
                user_class=request_user_class(),
            ).inc()
        except Exception:
            pass
        nearest_stations = find_nearest_stations(user_lat, user_lng, limit=limit, max_distance=max_distance)

        # PR #48.4: pseudonymized event log. Best-effort write — a DB
        # failure here must not break the user-facing flow. GDPR-safe:
        # session_hash is sha256 of session id (one-way), lat/lng
        # bucketed to 0.01° (~1km), browser_class from existing
        # observability bucketer, no IP, no full UA.
        try:
            from models import SubmitLocationEvent as _SLE
            from hashlib import sha256 as _sha256
            sess_id = request.cookies.get('session', '')
            sess_hash = _sha256((sess_id or '').encode('utf-8')).hexdigest() if sess_id else None
            db.session.add(_SLE(
                session_hash=sess_hash,
                user_id=session.get('user_id'),
                lat_bucket=round(user_lat, 2),
                lng_bucket=round(user_lng, 2),
                in_pl=True,
                browser_class=classify_user_agent(request.headers.get('User-Agent')),
                api_tier=getattr(g, 'api_tier', None),
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Could not record submit_location event")

        if nearest_stations is None or not nearest_stations.get('stations'):
            empty_result_total.inc()
            return jsonify({'stations': [], 'count': 0})
        return jsonify(nearest_stations)

    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid coordinates'}), 400
    except Exception:
        app.logger.exception("Error in submit_location")
        return jsonify({'error': 'An error occurred'}), 500

@app.route('/stations', methods=['GET'])
@limiter.limit("30 per minute")
@require_api_access(endpoint_label='stations')
def get_stations():
    try:
        user_lat = request.args.get('lat')
        user_lng = request.args.get('lng')

        if user_lat and user_lng:
            user_lat = float(user_lat)
            user_lng = float(user_lng)
            if not _coords_in_bounds(user_lat, user_lng):
                # PR #46.5 follow-up: match the /submit_location easter-egg
                # contract — return 200 with outside_pl=true and an empty
                # stations[] instead of 400. The frontend was hitting this
                # endpoint after the user clicked outside PL (geolocation
                # placed them in Belarus), and the 400 made globalFetch
                # bail into .catch — sidebar / pin never cleared. Same
                # marker as /submit_location so JS handles both uniformly.
                return jsonify({
                    'outside_pl': True,
                    'stations': [],
                    'count': 0,
                })
        else:
            user_location = session.get('user_location')
            if user_location:
                user_lat = user_location['lat']
                user_lng = user_location['lng']
            else:
                return jsonify({"error": "User location not set"}), 400

        max_distance = request.args.get('max_distance', default=None, type=float)
        limit = request.args.get('limit', default=9, type=int)

        if max_distance is not None:
            if max_distance < 0.1 or max_distance > 10:
                return jsonify({"error": "Invalid parameter", "message": "Max distance must be between 0.1 and 10 km. Please respect it."}), 400
            # Set limit to None when a valid max_distance is provided to focus on distance-based filtering
            limit = None
        elif limit is not None:
            # Validate limit if max_distance is not provided
            if limit < 1 or limit > 10:
                return jsonify({"error": "Invalid parameter", "message": "Limit cannot exceed 10. Please respect it."}), 400

        frequency_bands = request.args.getlist('frequency_bands')
        raw_service_providers = request.args.getlist('service_provider')

        cleaned_service_providers = [provider.rstrip("'") for provider in raw_service_providers]

        # Track which providers / bands users actually filter on — answers
        # "what's worth highlighting in the UI" once we have promotion-driven
        # traffic. Bounded cardinality (≤4 providers, ≤14 bands).
        for provider in cleaned_service_providers:
            provider_filter_used_total.labels(provider=provider).inc()
        for band in frequency_bands:
            band_filter_used_total.labels(band=band).inc()

        station_search_total.labels(endpoint='stations').inc()
        result = find_nearest_stations(user_lat, user_lng, max_distance=max_distance, limit=limit, service_providers=cleaned_service_providers, frequency_bands=frequency_bands)
        stations = result.get("stations", [])
        stations_count = result.get("count", 0)
        if stations_count == 0:
            empty_result_total.inc()

        if frequency_bands:
            stations = [station for station in stations if set(frequency_bands).issubset(set(station['frequency_bands']))]

        if cleaned_service_providers:
            stations = [station for station in stations if station['service_provider'] in cleaned_service_providers]

        stations_data = [{
            'basestation_id': station['basestation_id'], 
            'latitude': station['latitude'],              
            'longitude': station['longitude'],            
            'frequency_bands': station['frequency_bands'], 
            'city': station['city'],                     
            'location': station['location'],              
            'service_provider': station['service_provider'],
            'distance': station['distance']
        } for station in stations]

        filtered_count = len(stations_data)

        return jsonify({"stations": stations_data, "count": filtered_count})

    except (TypeError, ValueError):
        return jsonify({"error": "Invalid parameter values."}), 400
    except Exception:
        app.logger.exception("Error fetching stations")
        return jsonify({"error": "An error occurred while fetching stations."}), 500

@app.route('/find_station', methods=['GET'])
@require_api_access(endpoint_label='find_station')
def find_station():
    basestation_id = request.args.get('basestation_id', type=str)
    if not basestation_id or len(basestation_id) > 7 or not re.match("^[A-Za-z0-9]+$", basestation_id):
        return jsonify({"error": "Request cannot be processed"}), 400

    # Honeypot: known fake IDs return 404 (looks like a normal miss to the
    # caller) but increment a tripwire counter so we know we're being scraped.
    if is_honeypot(basestation_id):
        record_honeypot_hit(basestation_id, endpoint='find_station')
        return jsonify({"error": "Station not found"}), 404

    station = BaseStation.query.filter_by(basestation_id=basestation_id).first()
    if station:
        station_data = {
            'basestation_id': station.basestation_id,
            'latitude': station.latitude,
            'longitude': station.longitude,
            'frequency_bands': station.frequency_band,
            'city': station.city,
            'location': station.location,
            'service_provider': station.service_provider,
        }
        return jsonify(station_data)
    else:
        return jsonify({"error": "Station not found"}), 404

@app.route('/search_stations', methods=['GET'])
@limiter.limit("30 per minute")
@require_api_access(endpoint_label='search_stations')
def search_stations():
    station_search_total.labels(endpoint='search_stations').inc()
    query = request.args.get('q', type=str, default='')

    # Honeypot: prefix-search for a known-fake ID also trips the wire.
    if query and is_honeypot(query):
        record_honeypot_hit(query, endpoint='search_stations')
        return jsonify({"stations": []})
    limit = request.args.get('limit', type=int, default=5)

    if not query or len(query) < 2 or len(query) > 7:
        return jsonify({"stations": []})

    if not re.match("^[A-Za-z0-9]+$", query):
        return jsonify({"stations": []})

    # Search for stations with basestation_id starting with the query
    stations = BaseStation.query.filter(
        BaseStation.basestation_id.like(f'{query.upper()}%')
    ).limit(limit).all()

    stations_data = [{
        'basestation_id': s.basestation_id,
        'latitude': s.latitude,
        'longitude': s.longitude,
        'city': s.city,
        'service_provider': s.service_provider,
    } for s in stations]

    return jsonify({"stations": stations_data})


# PR #47: per-band coverage-gap detection. For each frequency band in
# the dataset, returns the distance to the nearest BTS of that band
# and a boolean has_coverage based on band-specific thresholds (low
# bands penetrate further so they get bigger thresholds; see
# queries.COVERAGE_THRESHOLDS_KM). Surfaced in the sidebar after every
# map click so users see "you're in a 5G dead zone here" without
# having to interpret distance numbers.
@app.route('/coverage_gaps', methods=['GET'])
@limiter.limit("30 per minute")
@require_api_access(endpoint_label='coverage_gaps')
def coverage_gaps():
    try:
        user_lat = float(request.args.get('lat'))
        user_lng = float(request.args.get('lng'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid lat/lng'}), 400
    if not _coords_in_bounds(user_lat, user_lng):
        # Match the easter-egg contract — 200 with outside_pl flag and
        # an empty result so the JS handles it uniformly with /stations.
        return jsonify({
            'outside_pl': True,
            'gaps': [],
            'summary': {'total_bands': 0, 'covered': 0, 'dead': 0},
        })
    return jsonify(find_coverage_gaps(user_lat, user_lng))


@app.route('/robots.txt')
def robots_txt():
    """Search-engine crawler directives. Allows public pages, blocks API
    + auth + admin + embed widget surfaces (no SEO value, also reduces
    scrape volume from well-behaved crawlers)."""
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /data\n"
        "Allow: /stats\n"
        "Allow: /tips\n"
        "Allow: /privacy\n"
        "Disallow: /api/\n"
        "Disallow: /embed/\n"
        "Disallow: /account\n"
        "Disallow: /unsubscribe/\n"
        "Disallow: /login\n"
        "Disallow: /register\n"
        "Disallow: /logout\n"
        "Disallow: /metrics\n"
        "Disallow: /healthz\n"
        "Disallow: /find_station\n"
        "Disallow: /search_stations\n"
        "Disallow: /stations\n"
        "Disallow: /submit_location\n"
        "Disallow: /session_check\n"
        "\n"
        f"Sitemap: {settings.canonical_origin}/sitemap.xml\n"
    )
    from flask import Response
    return Response(body, mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap_xml():
    """Lists the public pages we want indexed. Static set — small enough
    to inline. Add per-station sitemap pages later if /find_station/<id>
    becomes a public surface."""
    from flask import Response
    pages = [
        ('/',     '1.0', 'daily'),
        ('/data', '0.8', 'monthly'),
        ('/stats', '0.8', 'monthly'),
        ('/tips', '0.7', 'monthly'),
        ('/privacy', '0.3', 'yearly'),
    ]
    origin = settings.canonical_origin
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, prio, freq in pages:
        body.append(f'  <url>')
        body.append(f'    <loc>{origin}{path}</loc>')
        body.append(f'    <changefreq>{freq}</changefreq>')
        body.append(f'    <priority>{prio}</priority>')
        body.append(f'  </url>')
    body.append('</urlset>')
    return Response('\n'.join(body), mimetype='application/xml')


@app.route('/embed/widget')
def embed_widget():
    """Embeddable map widget for client iframes.

    Stripped chrome (no header, no footer, no auth UI) so the embed looks
    like a native part of the embedding page. CSP frame-ancestors is
    overridden by the after_request hook based on EMBED_ALLOWED_ORIGINS.

    Query params:
      lat, lng — optional starting coordinate (defaults to Warsaw)
      zoom     — optional zoom level (default 12)
      limit    — max stations to show (default 5, max 10)
    """
    raw_lat = request.args.get('lat')
    raw_lng = request.args.get('lng')
    has_coords = raw_lat is not None and raw_lng is not None
    try:
        lat = float(raw_lat) if has_coords else 52.2297
        lng = float(raw_lng) if has_coords else 21.0122
        zoom = max(5, min(int(request.args.get('zoom', 12 if has_coords else 6)), 17))
        limit = max(1, min(int(request.args.get('limit', 5)), 10))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid parameters'}), 400

    if has_coords and not _coords_in_bounds(lat, lng):
        return jsonify({'error': 'Coordinates outside supported area'}), 400

    # auto=1 → request browser geolocation immediately on page load.
    # When no coords were provided, default to auto-prompt; otherwise
    # only auto-prompt if explicitly requested by query.
    auto = request.args.get('auto', '0' if has_coords else '1') in ('1', 'true', 'yes')

    return render_template(
        'embed.html',
        lat=lat, lng=lng, zoom=zoom, limit=limit,
        auto_locate=auto,
        has_coords=has_coords,
        canonical_origin=settings.canonical_origin,
    )


# Auth routes (register / login / logout / session_check / account /
# regenerate_api_key) live in the auth_routes module as a Flask blueprint.
# Wired here so dependency order (db, bcrypt, limiter, validate_csrf, etc.)
# is unambiguous.
from auth_routes import register_auth_routes
register_auth_routes(
    app,
    bcrypt=bcrypt,
    db=db,
    limiter=limiter,
    validate_csrf=validate_csrf,
    generate_api_key=generate_api_key,
    csrf_failures_total=csrf_failures_total,
    login_failures_total=login_failures_total,
)


# ─────────────────────────────────────────────────────────────────────────────
# /api/v1/ — versioned aliases of the public endpoints. The legacy unprefixed
# routes above stay for back-compat (browser JS still calls them); the
# Swagger UI / OpenAPI spec only documents the /api/v1/ surface.
# Each wrapper carries the YAML docstring flasgger reads from.
# ─────────────────────────────────────────────────────────────────────────────

def api_v1_get_stations():
    """
    Find stations near a coordinate.
    ---
    tags: [Stations]
    parameters:
      - in: query
        name: lat
        required: true
        schema: {type: number, format: double, minimum: 49.0, maximum: 55.5}
        description: Latitude (Polish national bounds).
        example: 52.2297
      - in: query
        name: lng
        required: true
        schema: {type: number, format: double, minimum: 14.0, maximum: 24.2}
        description: Longitude.
        example: 21.0122
      - in: query
        name: limit
        schema: {type: integer, minimum: 1, maximum: 10, default: 9}
      - in: query
        name: max_distance
        schema: {type: number, minimum: 0.1, maximum: 10}
        description: Filter to stations within this radius (km). When set, `limit` is ignored.
      - in: query
        name: service_provider
        schema:
          type: array
          items:
            type: string
            enum:
              - Orange Polska S.A.
              - P4 sp. z o.o.
              - Polkomtel sp. z o.o.
              - T-Mobile Polska S.A.
        description: Repeat to OR-filter by multiple operators.
      - in: query
        name: frequency_bands
        schema:
          type: array
          items: {type: string}
        description: Repeat to filter by 5G/LTE/UMTS/GSM bands (e.g. LTE1800, 5G2100).
    responses:
      200:
        description: Stations within bounds, sorted by distance ascending.
        content:
          application/json:
            schema: {$ref: '#/components/schemas/StationsResponse'}
      400:
        description: Invalid parameters (out-of-bounds coords, limit > 10, etc.).
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Error'}
      403:
        description: No API key and no same-origin Referer.
      429:
        description: Tier rate limit exceeded.
    """
    return get_stations()


def api_v1_find_station():
    """
    Lookup a single station by ID.
    ---
    tags: [Stations]
    parameters:
      - in: query
        name: basestation_id
        required: true
        schema: {type: string, pattern: '^[A-Za-z0-9]{1,7}$'}
        example: T1234
    responses:
      200:
        description: Station found.
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Station'}
      400:
        description: Invalid ID format (non-alphanumeric, > 7 chars).
      403:
        description: No API key and no same-origin Referer.
      404:
        description: No station with that ID.
    """
    return find_station()


def api_v1_search_stations():
    """
    Autocomplete BTS IDs by prefix.
    ---
    tags: [Stations]
    parameters:
      - in: query
        name: q
        required: true
        schema: {type: string, minLength: 2, maxLength: 7, pattern: '^[A-Za-z0-9]+$'}
        description: Prefix to match (case-insensitive).
        example: T10
      - in: query
        name: limit
        schema: {type: integer, default: 5}
    responses:
      200:
        description: Matching stations (may be empty list).
        content:
          application/json:
            schema:
              type: object
              properties:
                stations:
                  type: array
                  items:
                    type: object
                    properties:
                      basestation_id: {type: string}
                      latitude: {type: number}
                      longitude: {type: number}
                      city: {type: string}
                      service_provider: {type: string}
      403:
        description: No API key and no same-origin Referer.
    """
    return search_stations()


def api_v1_submit_location():
    """
    Submit user location and return nearest stations.
    ---
    tags: [Stations]
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [lat, lng]
            properties:
              lat: {type: number, minimum: 49.0, maximum: 55.5}
              lng: {type: number, minimum: 14.0, maximum: 24.2}
              limit: {type: integer, minimum: 1, maximum: 10, default: 9}
              max_distance: {type: number, minimum: 0.1, maximum: 10}
    parameters:
      - in: header
        name: X-CSRF-Token
        required: true
        schema: {type: string}
        description: From the `<meta name="csrf-token">` tag on /. Required for POST.
    responses:
      200:
        description: Nearest stations, plus the location is saved on the session.
        content:
          application/json:
            schema: {$ref: '#/components/schemas/StationsResponse'}
      400:
        description: Out-of-bounds coords or missing lat/lng.
      403:
        description: Missing or wrong X-CSRF-Token.
      429:
        description: Rate limit (30 per minute).
    """
    return submit_location()


def api_v1_healthz():
    """
    Liveness probe. Cheap (no DB hit), no auth.
    ---
    tags: [System]
    responses:
      200:
        description: App is alive.
        content:
          application/json:
            schema:
              type: object
              properties:
                status: {type: string, example: ok}
                service: {type: string, example: signal-scout}
                version: {type: string, example: dev}
    """
    from flask import current_app
    return current_app.view_functions['healthz']()


def api_v1_coverage_gaps():
    """
    Per-band coverage check at a single coordinate.
    ---
    tags: [Stations]
    description: |
      For each frequency band present in the dataset, returns the
      distance to the nearest BTS of that band and whether that
      distance falls inside the band-specific "poor coverage"
      threshold. A "gap" is a band whose nearest station is farther
      than the threshold — meaning a phone configured for that band
      would lose signal here.

      Thresholds (km): high-band (5G3600, LTE2600) ≤1.5; mid-band
      (5G2100, LTE2100, LTE1800, UMTS2100) ≤2; low-band (LTE800,
      L900, GSM900) ≤5; default ≤3.
    parameters:
      - in: query
        name: lat
        required: true
        schema: {type: number, format: double, minimum: 49.0, maximum: 55.5}
        example: 52.2297
      - in: query
        name: lng
        required: true
        schema: {type: number, format: double, minimum: 14.0, maximum: 24.2}
        example: 21.0122
    responses:
      200:
        description: |
          Per-band coverage verdicts. When the coordinate is outside
          PL bounds, returns `{outside_pl: true, gaps: [], summary: {…}}`
          (200, not 400) so the JS client handles it uniformly with
          /submit_location.
        content:
          application/json:
            schema:
              type: object
              properties:
                gaps:
                  type: array
                  items:
                    type: object
                    properties:
                      band: {type: string, example: "5G3600"}
                      nearest_distance_km: {type: number, example: 0.14}
                      nearest_lat: {type: number, example: 52.2298}
                      nearest_lng: {type: number, example: 21.0125}
                      nearest_basestation_id: {type: string, example: "T1234"}
                      nearest_service_provider: {type: string, example: "Orange Polska S.A."}
                      nearest_city: {type: string, example: "Warszawa"}
                      nearest_location: {type: string, example: "Złota 44, 39"}
                      nearest_frequency_bands:
                        type: array
                        items: {type: string}
                        example: ["5G3600", "LTE2600", "LTE1800"]
                      threshold_km: {type: number, example: 1.5}
                      has_coverage: {type: boolean, example: true}
                summary:
                  type: object
                  properties:
                    total_bands: {type: integer, example: 14}
                    covered: {type: integer, example: 8}
                    dead: {type: integer, example: 6}
                outside_pl: {type: boolean, example: false}
      400:
        description: Invalid lat/lng parsing.
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Error'}
      403:
        description: No API key and no same-origin Referer.
      429:
        description: Tier rate limit exceeded.
    """
    return coverage_gaps()


app.add_url_rule('/api/v1/stations', endpoint='api_v1_stations',
                 view_func=api_v1_get_stations, methods=['GET'])
app.add_url_rule('/api/v1/find_station', endpoint='api_v1_find_station',
                 view_func=api_v1_find_station, methods=['GET'])
app.add_url_rule('/api/v1/search_stations', endpoint='api_v1_search_stations',
                 view_func=api_v1_search_stations, methods=['GET'])
app.add_url_rule('/api/v1/submit_location', endpoint='api_v1_submit_location',
                 view_func=api_v1_submit_location, methods=['POST'])
app.add_url_rule('/api/v1/coverage_gaps', endpoint='api_v1_coverage_gaps',
                 view_func=api_v1_coverage_gaps, methods=['GET'])
app.add_url_rule('/api/v1/healthz', endpoint='api_v1_healthz',
                 view_func=api_v1_healthz, methods=['GET'])


if __name__ == '__main__':
    app.run(debug=settings.debug,
            host='0.0.0.0',
            port=settings.port)
            #ssl_context=('/etc/ssl/localcerts/localhost+2.pem', '/etc/ssl/localcerts/localhost+2-key.pem'))
