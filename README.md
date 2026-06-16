# Signal-Scout

Find the nearest cellular base stations across Poland on an interactive map.
Public web app + documented JSON API. Live: <https://www.signal-scout.com>

[![CI](https://github.com/hch155/signal-scout/actions/workflows/ci.yaml/badge.svg)](https://github.com/hch155/signal-scout/actions/workflows/ci.yaml)

## Numbers

| | |
|---|---|
| Dataset | ~22k unique BTS / 188k+ frequency-band rows |
| Operators / bands | 4 operators, all current bands (5G / LTE / UMTS / GSM) |
| Query latency (server-side) | `/stations` p95 ~28 ms on the 188k-row prod dataset — compute only |
| End-to-end latency | `/stations` p95 ~170 ms, median ~140 ms from PL — network-dominated (~125 ms floor: Hetzner edge + Tailscale mesh + home LXC) |
| Perf optimization | 2024: page response ~4 s → ~40 ms (latitude segmentation, Cloud Run). 2026: query p95 186 → 48 ms (−74%, SQL grouping + composite index). Distinct metrics/eras — see [case study](docs/case-study-performance.md). |
| Tests | 477 passing (unit + integration + Playwright E2E) |
| CI/CD | lint → test → trivy fs → build → trivy image → promote → staging → prod (smoke + auto-rollback) |
| Hosting | self-hosted, ~€7/mo cash (Hetzner edge + home LXC + Tailscale) |
| History | solo project, 1181 commits since 2024; build log at [/build-log](https://www.signal-scout.com/build-log) |

## What's in it

- **Map UI** — Leaflet, click anywhere in PL for the nearest stations,
  filter by provider / frequency band, distance-based RSRP color coding,
  answer-first verdict card ("is this spot covered").
- **Public API** — same data, machine-readable. Swagger UI at
  `/api/v1/docs/`, OpenAPI 3 spec at `/api/v1/openapi.json`.
- **Compass mode** — mobile users navigate to a station with live bearing.
- **Saved locations + coverage alerts** — registered users save up to 20
  named places; on the monthly dataset refresh they get a diff (added /
  removed BTS, band changes) and an optional email alert.

## Architecture

```
Browser (Leaflet + vanilla JS)
   │  GET /, /stations, …             POST /login, /submit_location
   │       Referer-gated               CSRF-token-gated
   ▼
Hetzner edge (CX23, Falkenstein) — NPM reverse proxy + TLS (Let's Encrypt)
   │  signal-scout.com / staging.signal-scout.com
   │  Cloudflare DNS (DNS-only)
   │
   │  Tailscale mesh tunnel (edge ↔ home LXC, ~42 ms hop)
   ▼
the prod host on NUC_HOST (Proxmox)
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
   ├── users.db    (auth, sessions, snapshots — Alembic-owned schema)
   └── /metrics    (bearer-auth Prometheus exposition; 404 when token unset)
                       │
                       │  HTTP scrape on LAN, per env
                       ▼
       Self-hosted observability (NUC)
       ├── Prometheus  — scrape, alert rules, SLO burn-rate
       ├── Grafana     — Signal-Scout dashboard (21 panels / 6 rows)
       ├── Zabbix 7.0  — pulls Prom + Plausible via HTTP-agent items
       │                 (single source of truth — no double scrape)
       └── Plausible   — cookie-less visitor analytics (GDPR-friendly)

   CI/CD: Forgejo Actions runner (the CI runner host) + Harbor registry (same NUC)
```

## Engineering depth

### Security

Two written audits (`docs/security-audit-2026-04-26.md`,
`docs/security-audit-2026-06-10.md`), each fix landed as a PR tied to a
finding ID.

- **Auth** — bcrypt (cost 12) + password regex; account lockout after 5
  failed logins (atomic SQL increment), extended to all bcrypt endpoints;
  session rotation on login with CSRF preserved across rotation;
  account-enumeration oracles closed (dummy bcrypt burn).
- **2FA** — TOTP (pyotp) + bcrypt-per-code recovery codes; replay
  protection within the validity window; half-session TTL.
- **Secrets** — TOTP secret **KMS-wrapped at rest** (`src/kms.py`, Noop
  default, Google backend flips on via env, legacy-plaintext read
  fallback); API keys stored **sha256-hashed** (full token shown once,
  `first8…last4` for recognition).
- **CSRF** — `hmac.compare_digest`, token rotation across the login
  privilege boundary; coverage on every state-changing POST.
- **Audit log** — tamper-evident hash chain on `audit_event`; GDPR IP
  redaction (`/24` v4, `/48` v6, first XFF hop only).
- **Headers** — strict CSP (`script-src 'self'`, no `unsafe-inline`), HSTS
  preload, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy,
  COOP, CORP. Leaflet + DOMPurify vendored same-origin (no CDN).
- **Honeypot** — reserved fake BTS IDs (`HONEYPOT_BTS_IDS`) return a
  normal-miss shape but page on lookup (scrape / data-leak detection).
- **Webhook** — SendGrid event webhook verified by ECDSA, fail-closed.
- **GDPR** — `/privacy` Art. 13 transparency notice; `/data-deletion`
  Art. 17 erasure with cascade across audit/locations/snapshots/keys.

### Observability

Three SRE frameworks, deliberately overlapping:

- **Four Golden Signals** — Latency / Traffic / Errors / Saturation
  (in-process `in_flight_requests` vs configured workers gauge).
- **RED** — Rate / Errors / Duration per resource
  (`api_requests_total{tier,endpoint,outcome}`).
- **USE** — Utilisation / Saturation / Errors of resources.
- **SLI/SLO + burn-rate** — availability 99.5%, `/stations` latency 95%
  under 500 ms, error-budget-remaining; fast-burn 14.4× + 28-day budget
  triggers in Zabbix.

Stack: Prometheus + Grafana (21 panels) + Zabbix 7.0 + Plausible, all
self-hosted on the NUC. Public `/status` page backed by the in-process
registry only — `compute_public_status()` never reads CSRF / login /
honeypot / API-key counters (privacy boundary enforced in code).

### CI/CD

Self-hosted Forgejo Actions runner (the CI runner host) + Harbor registry, on every
merge to `main`:

```
lint (ruff) → test → trivy fs → build + push Harbor (staging tag)
  → trivy image scan → promote (re-tag staging digest as prod, zero rebuild)
  → deploy-staging (ssh the prod host, compose up :8081, smoke)
  → deploy-prod    (ssh the prod host, compose up :8080, smoke,
                    auto-rollback on smoke fail via .env.bak)
```

Plus SBOM (syft, CycloneDX), pip-audit, bandit. "Build once, promote the
digest" guarantees staging and prod run identical bytes. A separate
monthly cron (`monthly-db-update.yml`) pulls fresh UKE data, rebuilds
`stations.db`, commits + pushes, which redeploys with the new dataset.

### Data

- **SQLite, read-heavy single-writer.** `stations.db` is read-only at
  runtime (188k rows), rebuilt out-of-band monthly — a perfect fit for
  SQLite's read concurrency without a server process. `users.db` is the
  only writer (WAL enabled), low write volume.
- **Alembic** owns the `users.db` schema (no boot-time create-all); the
  dataset date lives in `stations.db` metadata (`data_date`), not file
  mtime.
- **Monthly UKE refresh** via Forgejo cron; stats snapshot history is a
  `users.db` table (migrated off a baked JSONL).

> The UKE ingestion/parsing pipeline (`base_station_data/` + build scripts)
> is **not included in this public repo**. The built `stations.db` ships
> with the app so it runs end-to-end; the pipeline that produces it is kept
> private.

## Performance

Full write-ups: `docs/case-study-performance.md` (both eras) and
`src/content/build-log.md` (the chronological journal; live at `/build-log`).

- **2024 (Cloud Run, hand-measured):** ~4 s → 42 ms (~100×). The dominant
  win was algorithmic — bucketing rows by latitude segment. JS `--mangle`
  changed nothing measurable and is recorded as a null result.
- **2026 (self-hosted, SQL grouping):** moved per-request frequency-band
  grouping out of a Python loop into SQL `GROUP_CONCAT` + a composite index
  matching the query's filter shape. Mixed-endpoint p95 186 → 48 ms (−74%);
  found and fixed a pre-existing grouping bug in the same PR.
- **Today (measured 2026-06):** server-side compute is the fast part —
  `/stations` p95 ~28 ms on the prod dataset. End-to-end from PL is ~140 ms
  median / ~170 ms p95, **dominated by the network path** (~125 ms floor:
  edge + Tailscale mesh + home LXC), not compute. The two arcs above are
  *compute* optimizations measured with different tools/datasets/eras — they
  are not a single comparable series.
- A per-PR CI gate fires 100 requests at `/` and fails the build if p95 >
  500 ms; a daily smoke cron probes prod. Every perf-relevant change has a
  committed snapshot under `tests/results/`.

## Why this exists / build history

Solo side project, started in 2024 (earliest tree state 2023), 1181
commits. The build log (`src/content/build-log.md`, live at `/build-log`)
is the raw chronology: a hand-built Flask app on Cloud Run → algorithmic
perf work → self-hosted migration → security hardening → observability →
CI/CD.

## API

```bash
# Anonymous browser-style call (Referer required)
curl -H "Referer: https://signal-scout.com/" \
  "https://signal-scout.com/api/v1/stations?lat=52.23&lng=21.00&limit=5"

# With API key (no Referer needed, higher rate limit)
curl -H "X-API-Key: sk_..." \
  "https://signal-scout.com/api/v1/stations?lat=52.23&lng=21.00&limit=5"
```

Auth: `X-API-Key: <token>` header (generate at `/account`) or same-origin
browser request (cookies + Referer). Keys are sha256-hashed at rest — the
full token is shown only once at creation. Tiered rate limits: anonymous
10/min · free 60/min · pro 300/min · enterprise 3000/min.

Full schemas in Swagger UI at `/api/v1/docs/`. Public read endpoints
(Referer-gated for anonymous, X-API-Key bypass + tier limits):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/stations` | Nearest stations with optional provider/band filters |
| GET | `/api/v1/find_station?basestation_id=…` | Exact lookup by BTS ID |
| GET | `/api/v1/search_stations?q=…` | Autocomplete by ID prefix |
| GET | `/api/v1/coverage_gaps?lat=…&lng=…` | Per-band "is this spot dead?" verdict |
| POST | `/api/v1/submit_location` | Persist click location to session, return nearest |
| GET | `/api/v1/healthz` | Liveness probe (no auth) |
| GET | `/api/v1/openapi.json` | OpenAPI 3 spec |

Legacy unprefixed routes (`/stations`, `/find_station`, …) stay live for
back-compat. Full route inventory (auth, account, saved locations, ops):
see the Swagger UI and `src/app.py` / `src/auth_routes.py`.

## Local dev

```bash
git clone https://github.com/hch155/signal-scout.git
cd signal-scout
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r tests/requirements-test.txt
playwright install chromium                            # for E2E tests

PYTHONPATH=src python src/app.py
# → http://localhost:8080
```

Env vars are all optional in dev (defaults are safe). Notable ones:

| Var | What | Default |
|---|---|---|
| `ENV` | `PRODUCTION` enables HSTS-secure cookies + SECRET_KEY boot guard | (unset = dev) |
| `SECRET_KEY` | Flask session signing | random per process |
| `STATIONS_DB_PATH` / `USERS_DB_PATH` | Override DB paths | `src/instance/*.db` |
| `METRICS_BEARER_TOKEN` | If unset, `/metrics` returns 404 | (unset) |
| `HONEYPOT_BTS_IDS` | Comma-list of fake BTS IDs | (none) |
| `PLAUSIBLE_DOMAIN` / `PLAUSIBLE_SCRIPT_URL` | Analytics tracker | (unset → not rendered) |
| `APP_VERSION` | Reported by `/healthz` | `dev` |

See `src/config.py` for the full catalog (single source of truth).

## Tests

```bash
pytest tests/unit tests/integration                       # fast, default
pytest tests/unit tests/integration tests/e2e --browser chromium   # + E2E
pytest -m slow                                            # rate-limit tests
pytest -m smoke                                           # prod smoke (read-only)
```

477 passing (unit + integration + Playwright E2E). Coverage gate 80% in CI;
93% on `src/app.py` + `src/queries.py` + `src/models.py`.

## Docker

```bash
docker build -t signal-scout .
docker run -e SECRET_KEY=$(openssl rand -hex 32) -e ENV=PRODUCTION \
           -p 8080:8080 signal-scout
```

Multi-stage build, non-root `appuser` (UID 1000), `tini` PID 1,
HEALTHCHECK against `/healthz`. Image ~580 MB.

## Documentation

- `src/content/build-log.md` — raw chronological engineering journal (start here; live at `/build-log`).
- `docs/case-study-performance.md` — both performance eras + the CI/SLO
  machinery.
- `docs/migration-cloud-run-to-self-hosted.md` — the migration, including
  the honest cost analysis (this is *not* the cheapest option, and the doc
  says so).
- `docs/security-audit-2026-04-26.md`, `docs/security-audit-2026-06-10.md`
  — the two audits.
- `docs/CHANGELOG.md` — per-PR descriptions.
- `docs/ROADMAP.md` — deferred work.

## Contact

Questions or suggestions: hcylwik@gmail.com
