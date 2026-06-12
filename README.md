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
  - Keys are stored hashed at rest (SHA-256) — the full token is shown
    only once at creation; `/account` lists `first8…last4` for
    recognition. Keep your copy safe; lost keys require a regenerate.
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

Endpoints — full schemas in Swagger UI at `/api/v1/docs/`. Compact map:

**Public read API** (Referer-gated for anonymous; X-API-Key bypass + tier limits)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/stations` | Nearest stations with optional provider/band filters |
| GET | `/api/v1/find_station?basestation_id=…` | Exact lookup by BTS ID |
| GET | `/api/v1/search_stations?q=…` | Autocomplete by ID prefix |
| GET | `/api/v1/coverage_gaps?lat=…&lng=…` | Per-band "is this spot dead?" verdict (5G/LTE/UMTS/GSM) |
| POST | `/api/v1/submit_location` | Persist click location to session, return nearest stations |
| GET | `/api/v1/healthz` | Liveness probe (no auth) |
| GET | `/api/v1/openapi.json` | OpenAPI 3 spec |

Legacy unprefixed routes (`/stations`, `/find_station`, `/search_stations`,
`/coverage_gaps`, `/submit_location`, `/healthz`) stay live for back-compat.

**Site pages** (HTML, no auth)

| Path | Purpose |
|------|---------|
| `/` | Map (Leaflet + sidebar) |
| `/data` | About the dataset (markdown) |
| `/stats` | Per-operator coverage stats |
| `/tips` | Tips & tricks (registered users get extended version) |
| `/tips/content` | JSON content fetcher used by `/tips` page (anon vs registered split) |
| `/privacy` | GDPR Art. 13 transparency notice — what we collect, why, retention, user rights |
| `/status` | Customer-facing service health (uptime %, search latency, requests/day) |
| `/embed/widget` | Embeddable widget (`?lat=…&lng=…&zoom=…`) for third-party iframes |
| `/favicon.ico`, `/robots.txt`, `/sitemap.xml` | SEO + browser-mandated assets |

**Auth & account** (POST unless noted; CSRF-required)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/register` | Create account (email + password) |
| POST | `/login` | Step 1: password. Returns `totp_required` if 2FA on. |
| POST | `/login/totp` | Step 2: TOTP code or one-shot recovery code |
| GET | `/auth/google/login` | Start Google OAuth flow (hidden if `GOOGLE_OAUTH_CLIENT_ID` unset) |
| GET | `/auth/google/callback` | Google OAuth redirect target |
| GET | `/auth/github/login` | Start GitHub OAuth flow (hidden if `GITHUB_OAUTH_CLIENT_ID` unset) |
| GET | `/auth/github/callback` | GitHub OAuth redirect target |
| POST | `/logout` | Clear session |
| GET  | `/session_check` | Returns `{logged_in: bool}` |
| GET  | `/account` | Account dashboard |
| POST | `/account/profile` | Update company name |
| POST | `/account/password` | Change password (rotates session) |
| POST | `/account/delete` | Delete account + cascade audit/snapshots |
| POST | `/account/regenerate_api_key` | Rotate the legacy default key |
| POST | `/account/keys` | Create a new named API key (multi-key system) |
| POST | `/account/keys/<id>/revoke` | Revoke a key (soft-delete) |
| POST | `/account/2fa/setup` | Begin TOTP enrollment (returns secret + QR + URI) |
| POST | `/account/2fa/verify` | Confirm enrollment with current code; mints recovery codes |
| POST | `/account/2fa/regenerate` | Mint a new TOTP secret without disabling 2FA |
| POST | `/account/2fa/disable` | Turn 2FA off (requires password + current code) |

**Saved locations** (multi-named places per user; PR #30)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/account/locations` | Create a saved location |
| GET  | `/account/locations/<id>` | View one |
| POST | `/account/locations/<id>` | Update name/description/coords/radius/alerting |
| POST | `/account/locations/<id>/delete` | Delete (cascades snapshots) |
| POST | `/account/locations/<id>/snapshot` | Capture station snapshot now |
| GET  | `/account/locations/<id>/changes` | Diff feed (added/removed BTS over time) |
| POST | `/account/snapshot` | Legacy: snapshot at the user's single saved location |
| GET  | `/account/changes` | Legacy single-location diff feed |

**Ops & metrics**

| Path | Purpose | Auth |
|------|---------|------|
| `/healthz` | Liveness — does NOT touch DB | open |
| `/metrics` | Prometheus exposition | bearer (`METRICS_BEARER_TOKEN`) — 404 when unset |
| `/api/v1/docs/` | Swagger UI | open |

## Architecture

```
Browser (Leaflet + vanilla JS)
   │  GET /, /stations, …             POST /login, /submit_location
   │       Referer-gated               CSRF-token-gated
   ▼
Hetzner edge (CX23, NPM @ HETZNER_EDGE_IP)  — TLS + reverse proxy
   │  signal-scout.com / staging.signal-scout.com
   │
   │  Tailscale mesh tunnel (edge ↔ home LXC)
   ▼
the prod host on NUC_HOST (LXC_LAN_IP)
   │  Docker compose stacks:
   │    /opt/stacks/signal-scout-prod      → app on :8080
   │    /opt/stacks/signal-scout-staging   → app on :8081
   │
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
   ├── stations.db (read-only, monthly UKE refresh via Forgejo Actions)
   ├── users.db    (Flask-Session + auth)
   └── /metrics    (bearer-auth Prometheus exposition)
                       │
                       │  HTTP scrape on LAN, 30s, per env
                       ▼
       Self-hosted observability (NUC, /opt/monitoring-stack/)
       ├── Prometheus      v2.55.1  — scrape, alert rules
       ├── Alertmanager    v0.27.0  — routing (default config; wire
       │                              email / Telegram / Slack receiver
       │                              in alertmanager.yml when needed)
       └── Grafana         v11.3.1  — Signal-Scout dashboard
                                       (15 panels — RPS, latency,
                                       errors, security, product)

       Self-hosted analytics (NUC, ops/homelab-integration/plausible/)
       └── Plausible       v3.0.0   — visitors, sources, countries,
                                       trends (cookie-less, GDPR-friendly,
                                       no banner needed)

       Self-hosted alerts + reports (NUC)
       └── Zabbix          7.0.25   — pulls Prom & Plausible via
                                       HTTP-agent items (single source
                                       of truth — no double scrape).
                                       16-widget dashboard, 5 triggers.
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

Self-hosted on the prod host (NUC_HOST), promoted from a Harbor-cached staging
image. Pipeline driven by `.forgejo/workflows/ci-cd.yml` on every merge to
`main` and runs on a self-hosted Forgejo runner (the CI runner host on the same NUC):

```
lint → test → trivy fs → build + push Harbor (staging tag)
     → trivy image scan → promote (re-tag staging digest as prod, zero rebuild)
     → deploy-staging (ssh the prod host, compose pull+up app on :8081, smoke)
     → deploy-prod    (ssh the prod host, compose pull+up app on :8080, smoke,
                        auto-rollback on smoke fail via .env.bak)
```

Required Forgejo Actions secrets:

- `HARBOR_USER`, `HARBOR_PASSWORD` — image registry auth
- `LXC_DEPLOY_SSH_KEY` — SSH key to the prod host used by the deploy jobs
- `METRICS_BEARER_TOKEN_PROD`, `METRICS_BEARER_TOKEN_STAGING` — scrape auth per env
- `FORGEJO_PUSH_TOKEN` — PAT with `write:repository` scope, used by the monthly DB-update workflow to commit + push the refreshed `stations.db`
- `PLAUSIBLE_DOMAIN`, `PLAUSIBLE_SCRIPT_URL` — analytics tracker (optional)

`SECRET_KEY` lives in `/opt/stacks/signal-scout-prod/.env` on the prod host
(not in CI) — the deploy job doesn't write it, the container reads it
on boot.

A separate `.forgejo/workflows/monthly-db-update.yml` runs on cron
(`15 19 27 * *`, ~21:15 Warsaw on the 27th) — pulls fresh UKE data,
rebuilds `stations.db`, commits + pushes back via `FORGEJO_PUSH_TOKEN`;
that commit then drives `ci-cd.yml` to rebuild + redeploy with the new
dataset.

For homelab observability deploy, see `ops/homelab-integration/README.md`.

## Documentation

- Mobile (Capacitor iOS/Android wrappers) is parked on the `mobile-archive`
  branch until store publication is back on the table
- `docs/CHANGELOG.md` — per-PR descriptions of recent work
- `docs/ROADMAP.md` — what's deferred for future PRs
- `ops/README.md` — observability stack on a NUC via Portainer
- `ops/homelab-integration/README.md` — drop-in snippets for an existing
  homelab Prometheus/Grafana stack

## Contact

Questions or suggestions: hcylwik@gmail.com
