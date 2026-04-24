# Signal-Scout

[Signal-Scout](https://www.signal-scout.com) — find the nearest cellular
base stations across Poland (~22k unique BTS / 188k+ frequency-band rows, 4 operators, all current bands)
on an interactive Leaflet map. Public web app + documented JSON API.

[![CI](https://github.com/hch155/signal-scout/actions/workflows/ci.yaml/badge.svg)](https://github.com/hch155/signal-scout/actions/workflows/ci.yaml)

---

## What's in the box

- **Map UI** — Leaflet, click anywhere in PL to see the nearest stations,
  filter by provider / frequency band, distance-based RSRP color coding.
- **Compass mode** — mobile users navigate to a station with live bearing.
- **Public API** — same data, machine-readable.
  - Swagger UI: `https://signal-scout.com/api/v1/docs/`
  - OpenAPI 3.0 spec: `https://signal-scout.com/api/v1/openapi.json`
  - Auth: `X-API-Key: <token>` header (generate at `/account` after signup)
    or same-origin browser request (cookies + Referer).
  - Tiered rate limits: anonymous 10/min · free 60/min · pro 300/min ·
    enterprise 3000/min.

## API at a glance

```bash
# Anonymous browser-style call (Referer required)
curl -H "Referer: https://signal-scout.com/" \
  "https://signal-scout.com/api/v1/stations?lat=52.23&lng=21.00&limit=5"

# With API key (no Referer needed, higher rate limit)
curl -H "X-API-Key: sk_..." \
  "https://signal-scout.com/api/v1/stations?lat=52.23&lng=21.00&limit=5"
```

Endpoints (full schemas in Swagger UI):
- `GET  /api/v1/stations` — nearest stations with optional provider/band filters
- `GET  /api/v1/find_station?basestation_id=…` — exact lookup
- `GET  /api/v1/search_stations?q=…` — autocomplete by ID prefix
- `POST /api/v1/submit_location` — same as `/api/v1/stations` but persists location to session
- `GET  /api/v1/healthz` — liveness probe (no auth)

Legacy unprefixed routes (`/stations`, `/find_station`, `/search_stations`,
`/submit_location`) stay live for back-compat.

## Architecture

```
Browser (Leaflet + vanilla JS)
   │  GET /, /stations, …             POST /login, /submit_location
   │       Referer-gated               CSRF-token-gated
   ▼
Cloud Run (signal-scout.run.app)
   │  Flask app — see src/
   │  ├── app.py             routes (stations, content, api/v1 aliases)
   │  ├── auth_routes.py     auth blueprint (register/login/logout/account)
   │  ├── api_access.py      same-origin gate + API key + honeypot
   │  ├── api_docs.py        OpenAPI spec + Swagger UI
   │  ├── observability.py   Prometheus metrics + /healthz
   │  ├── config.py          env-driven settings (single source of truth)
   │  ├── queries.py         SQLAlchemy queries
   │  └── models.py          BaseStation + User
   │
   ├── stations.db (read-only, monthly UKE refresh via GHA)
   ├── users.db    (Flask-Session + auth)
   └── /metrics    (bearer-auth Prometheus exposition)
                       │
                       │  HTTPS scrape, 60s
                       ▼
       Self-hosted observability (NUC, ops/homelab-integration)
       ├── Prometheus 3.x   — scrape, alerts → Telegram
       ├── Alertmanager     — routing
       └── Grafana 11.x     — dashboards (15 panels)

       Self-hosted analytics (NUC, ops/homelab-integration)
       └── Plausible        — visitors, sources, countries, trends
                              (cookie-less, GDPR-friendly)
```

## Security posture

| Layer        | What's enforced                                                     |
|--------------|---------------------------------------------------------------------|
| Headers      | CSP (no `unsafe-inline` in `script-src`), HSTS, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, COOP, CORP |
| Frontend     | Every user-controlled string is `escapeHtml()`-escaped; SRI on Leaflet + DOMPurify CDN scripts; no inline event handlers (CSP-strict) |
| CSRF         | `X-CSRF-Token` header (or `_csrf_token` form field) on every state-changing POST; rotated through login session-fixation defense |
| API keys     | Per-user 32-byte URL-safe token; X-API-Key header; tier-based rate limits |
| Honeypot     | Reserved fake BTS IDs (set via `HONEYPOT_BTS_IDS`) trigger paging alert when looked up — scrape & data-leak detection |
| Rate limits  | Per-tier (`anonymous` / `free` / `pro` / `enterprise`); 429 metric + alert on sustained spike |
| Logging      | `logger.exception()` for stack traces (server-side only); generic 500 message to client |
| Auth         | bcrypt hashing; password regex (8+ chars, mixed case, digit, special); session rotation on login; CSRF preserved across rotation |
| Container    | Multistage Dockerfile, non-root `appuser` (UID 1000), `tini` PID 1, no compilers in runtime image, HEALTHCHECK against `/healthz` |
| Supply chain | Trivy fs+image scan in CI (HIGH/CRITICAL), pip-audit, bandit, syft SBOM artifact (CycloneDX, 90-day retention) |
| Repo         | `gunicorn.sh` (info-disclosure script) removed; `terraform/`, `aws/`, `helm/` (dead infra) removed |

## Observability

`/metrics` exposes (bearer-auth, gated by `METRICS_BEARER_TOKEN` — returns
404 when unset):

- HTTP request latency / count / status (auto, prometheus-flask-exporter)
- `signal_scout_csrf_failures_total{endpoint}`
- `signal_scout_login_failures_total`
- `signal_scout_rate_limit_hits_total{endpoint}`
- `signal_scout_station_search_total{endpoint}`
- `signal_scout_provider_filter_used_total{provider}`
- `signal_scout_band_filter_used_total{band}`
- `signal_scout_compass_used_total`
- `signal_scout_empty_result_total`
- `signal_scout_requests_by_user_agent_class_total{ua_class}` — bucketed
  (googlebot/bingbot/other_bot/browser_chrome/firefox/safari/other/cli/unknown)
- `signal_scout_api_referer_blocked_total{endpoint}`
- `signal_scout_api_key_used_total{tier}`
- `signal_scout_honeypot_hit_total{endpoint}`
- `signal_scout_nearest_stations_compute_seconds` (histogram)

Pair Prometheus + Grafana with **Plausible** for visitor analytics:
- Prometheus answers "what's happening right now / is the bot traffic growing"
- Plausible answers "who's actually visiting / where from / how does it trend over months"

Deploy bundle: `ops/homelab-integration/` (Portainer-friendly, scrapes
Cloud Run with bearer auth from a self-hosted NUC stack).

## Local dev

```bash
git clone https://github.com/hch155/signal-scout.git
cd signal-scout
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r tests/requirements-test.txt
playwright install chromium                            # for E2E tests

# Run app
PYTHONPATH=src python src/app.py
# → http://localhost:8080
```

Environment variables (all optional in dev — defaults are safe):

| Var                       | What                                              | Default                          |
|---------------------------|---------------------------------------------------|----------------------------------|
| `ENV`                     | `PRODUCTION` enables HSTS-secure cookies          | (unset = dev mode)               |
| `SECRET_KEY`              | Flask session signing                             | random per process               |
| `STATIONS_DB_PATH`        | Override stations DB path                         | `src/instance/stations.db`       |
| `USERS_DB_PATH`           | Override users DB path                            | `src/instance/users.db`          |
| `SESSION_FILE_DIR`        | Where filesystem sessions live                    | `./flask_session/`               |
| `METRICS_BEARER_TOKEN`    | If unset, `/metrics` returns 404                  | (unset)                          |
| `HONEYPOT_BTS_IDS`        | Comma-list of fake BTS IDs                        | (none)                           |
| `PLAUSIBLE_DOMAIN`        | `data-domain` for Plausible script tag            | (unset → tracker not rendered)   |
| `PLAUSIBLE_SCRIPT_URL`    | Plausible script URL                              | (unset)                          |
| `APP_VERSION`             | Reported by `/healthz`                            | `dev`                            |

See `src/config.py` for the full catalog (single source of truth).

## Tests

```bash
# Unit + integration (fast, default)
pytest tests/unit tests/integration

# Plus Playwright E2E (chromium headless)
pytest tests/unit tests/integration tests/e2e --browser chromium

# Slow rate-limit tests (opt-in)
pytest -m slow

# Production smoke (read-only, polite, hits Cloud Run direct URL)
pytest -m smoke
```

156/156 currently green: 30 unit + 19 access-control + 13 OpenAPI + 13
observability + 14 auth + 9 stations + 11 security headers + … + 8 E2E.
Coverage 93% on `src/app.py` + `src/queries.py` + `src/models.py`.

## Docker

```bash
docker build -t signal-scout .
docker run -e SECRET_KEY=$(openssl rand -hex 32) \
           -e ENV=PRODUCTION \
           -p 8080:8080 signal-scout
```

Multi-stage build, non-root, HEALTHCHECK against `/healthz`. Image ~580MB.

## Deployment

Cloud Run (production) — pushed automatically by `.github/workflows/cd.yaml`
on every merge to `main`. Required GitHub Actions secrets:

- `SECRET_KEY` — Flask session signing
- `GCP_CREDENTIALS` — service account JSON for `gcloud`
- `METRICS_BEARER_TOKEN` — Prometheus scrape auth
- `PLAUSIBLE_DOMAIN`, `PLAUSIBLE_SCRIPT_URL` — analytics tracker (optional)

For homelab observability deploy, see `ops/homelab-integration/README.md`.

## Documentation

- `docs/CHANGELOG.md` — per-PR descriptions of recent work
- `docs/ROADMAP.md` — what's deferred for future PRs
- `ops/README.md` — observability stack on a NUC via Portainer
- `ops/homelab-integration/README.md` — drop-in snippets for an existing
  homelab Prometheus/Grafana stack

## Contact

Questions or suggestions: hcylwik@gmail.com
