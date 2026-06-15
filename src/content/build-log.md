# Build log

Engineering journal for Signal-Scout. Terse, dated, mined from the git
history (1181 commits, first commit 2024-01-10, earliest tree state
2023-02-13). Each entry: what / why / result / learned. Numbers are
hand-measured or pulled from committed snapshots, not estimated. Null
results are kept where they happened — that is the point of a lab notebook.

Order is chronological. Two big eras: a hand-built Flask app on Google
Cloud Run (2024 → early 2026), then the self-hosted migration and the
hardening/observability/CI build-out (2026).

---

## 2024 — hand-built Flask app on Google Cloud Run

**What.** Flask + Leaflet single-page map over a SQLite table of Polish
cellular base stations parsed from UKE permit data. Served from Cloud Run
in `europe-central2`, DNS via a Squarespace 302 redirect.

**Why.** Personal project: "where is the nearest 5G/LTE/UMTS/GSM tower,
and how far." No backend framework beyond Flask, no ORM tricks — get it
working, get it public.

**Result.** ~6k req/day, ~$0–2/mo on Cloud Run, ~99.5% uptime, zero ops
overhead, for ~18 months. Cold starts (`--min-instances=0`) cost ~1–3 s on
the first request after scale-to-zero.

**Learned.** Managed serverless is the correct default for a low-traffic
hobby project — the bill and the ops load are both near zero. Everything
after this is a deliberate trade against that baseline.

### Performance arc (2024, all hand-measured on Cloud Run)

Page response time, in seconds, measured by hand on a ThinkPad T490s
against live Cloud Run instances (1Gi–4Gi). "no-filter" = full result set
for a clicked point; "with-filter" = provider/band filter applied. This
predates all of the 2026 SQL-grouping work in
`case-study-performance.md` — it is the *first* performance era.

| Date / change | no-filter | with-filter | Note |
|---|---:|---:|---|
| Baseline (Cloud Run 1Gi–4Gi, T490s) | ~4–5.5 s | ~0.5 s | starting point |
| 2024-04-11 algorithmic change — latitude segmentation | 4 s → 0.5–1 s | 0.5 → 0.1 s | bucket rows by latitude band, scan only nearby buckets |
| JS minify (`esbuild --minify --compress`) | 0.5–0.6 → 0.366 s | 0.1 → 0.087 s | smaller payload, faster parse |
| JS minify `+ --mangle` | 0.366 → 0.366 s | — | **no change — recorded honestly** |
| Reduce latitude DB segment 0.3° → 0.1° | 0.5–1 → 0.12 s | 0.1 → 0.042 s | finer buckets, fewer rows scanned per query |

**Net 2024 arc: ~4 s → ~42 ms (~100×)**, entirely on Cloud Run, before the
2026 SQL-grouping era.

**Learned.**
- The big win was algorithmic (latitude segmentation), not the cloud.
  Bucketing the table by latitude and only scanning nearby buckets cut the
  no-filter path from seconds to sub-second; tightening the segment from
  0.3° to 0.1° took it the rest of the way.
- `--mangle` changed nothing measurable here. Identifier-shortening only
  helps when parse time dominates; payload size and DB scan time did. Kept
  the null result because pretending it helped would be a lie a reviewer
  could catch.
- Frontend minification (`--compress`) was real but second-order next to
  the DB-side wins.

---

## 2026-03 — push the hot loop into the database (Era 2)

**What.** The "nearest stations" query fetched rows and grouped frequency
bands per station **in Python**, once per request, over a 188k-row table.
Moved the grouping into SQL (`GROUP_CONCAT(DISTINCT frequency_band)` with
`GROUP BY latitude, longitude, service_provider`) and added a composite
index `ix_segment_provider_band` matching the query's filter shape.

**Why.** Python-side set-merging on every request is the textbook hot loop.

**Result** (`tests/results/perf_2026-03-27_sql_grouping.md`, full prod
dataset, A/B same machine):
- `POST /submit_location` avg −72% (85 → 24 ms), p95 −67%
- `GET /stations` avg −66% (32 → 11 ms), p95 −80% (98 → 20 ms)
- Mixed 100-req suite: avg −56%, **p95 185.6 → 48.0 ms (−74%)**

Bonus: writing the SQL forced a re-read of the old grouping logic, which
turned out to merge different operators sharing one mast into a single
station (10 locations). A pre-existing correctness bug, found *because* of
the perf work, fixed in the same PR.

**Learned.** The database beats a Python loop at set operations, and an
index is only as good as its match to the query's filter shape. Perf work
doubles as a correctness review.

## 2026-03 → 05 — make the benchmark an artifact, then a gate

**What.** Every perf-relevant change since gets a dated snapshot under
`tests/results/` (env, exact reproduce command, per-endpoint
min/avg/median/p95/max + error counts). PR #38 turned the budget into a
CI gate: boot gunicorn, fire 100 requests at `/`, fail the build if p95 >
500 ms (`PERF_P95_BUDGET_MS`), upload `perf.json` as an artifact. A daily
06:00 UTC smoke cron probes prod.

**Result.** Three diffable snapshots (03-27, 04-22, 05-09). Gated endpoint
sits at p95 = 1.01 ms against the 500 ms budget. The 05-09 snapshot caught
`POST /submit_location` drifting 19.5 → 22.7 ms avg (+16%) — root-caused to
the new tamper-evident audit-event write, a deliberate trade, now priced
and inside budget.

**Learned.** Continuous improvement isn't "every number goes down" — it's
that no number moves without being noticed and either fixed or consciously
accepted. A committed benchmark proves a trend; a terminal printout proves
nothing.

## 2026-04 — security audit #1 and the hardening sprint

**What.** Full security audit (`docs/security-audit-2026-04-26.md`,
critique follow-up 04-27) drove a sprint of fixes shipped as audit PRs A–L
plus the PR #1–#9 chain. Highlights:
- CSRF on every state-changing POST (`/submit_location` was the only one
  without `validate_csrf()`), `compare_digest`, token rotation across the
  login privilege boundary (session-fixation defense).
- Strict CSP — `script-src 'self'`, no `unsafe-inline`; required rewriting
  7 inline `onclick=` handlers to `addEventListener`. Plus HSTS (preload),
  X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, COOP, CORP.
- `escapeHtml()` on every user-controlled station field; fail-closed if
  DOMPurify is unavailable.
- Account lockout after 5 failed logins (atomic SQL increment), extended
  to all bcrypt endpoints; bcrypt cost 12; password-regex.
- 2FA TOTP (pyotp) + recovery codes (bcrypt per code), replay protection
  within the validity window, half-session TTL.
- Tamper-evident hash chain on `audit_event`.
- SHA-256-hashed API keys at rest (Stripe-style) — full token shown once,
  `first8…last4` for recognition.
- KMS-wrapped TOTP secret at rest (`src/kms.py`, `NoopKms` default,
  `GoogleKmsBackend` flips on via env, legacy-plaintext read fallback).
- Honeypot BTS rows (`HONEYPOT_BTS_IDS`) — a lookup returns a normal-miss
  shape but pages on hit (scrape / data-leak detection).
- GDPR audit-log IP redaction (`/24` v4, `/48` v6, first XFF hop only).

**Result.** Audit criticals closed; account-enumeration oracles closed
(dummy bcrypt burn on register/login/forgot-password). 156 → growing test
count stays green through the sprint.

**Learned.** A written audit with severity-tagged findings and a critique
pass is worth more than ad-hoc hardening. Each fix landed as its own PR
tied to a finding ID, so the trail is auditable.

## 2026-04 — observability: three SRE frameworks + public /status

**What.** Layered Four Golden Signals (Latency/Traffic/Errors/Saturation),
RED (Rate/Errors/Duration per resource, `api_requests_total{tier,endpoint,
outcome}`), and USE (in-process saturation gauge: in-flight vs configured
workers) on top of the existing Prometheus counters. Added explicit
SLIs/SLOs with burn-rate alerts: availability 99.5%, `/stations` latency
95% under 500 ms, error-budget-remaining; fast-burn 14.4× + 28-day budget
triggers wired into Zabbix. Customer-facing `/status` page backed by the
in-process registry only — `compute_public_status()` never reads CSRF /
login / honeypot / API-key counters (privacy boundary enforced in code).

**Result.** Grafana dashboard grew to 21 panels across 6 rows; Zabbix 7.0
template pulls Prometheus + Plausible via HTTP-agent items (single source
of truth, no double-scrape). `/metrics` is bearer-gated, returns 404 when
the token is unset.

**Learned.** The three frameworks overlap deliberately — Golden Signals
for the on-call glance, RED per endpoint/tier, USE for resource saturation.
A public status page is a forcing function: it makes you separate what's
safe to show from what isn't, in code.

## 2026-05-14/15 — migration: Cloud Run → Hetzner edge + home LXC + Tailscale

**What.** Moved signal-scout.com off Cloud Run to a hybrid: app in a
privileged LXC under Proxmox on a home NUC_HOST, Hetzner CX23 in
Falkenstein as the edge reverse proxy (Nginx Proxy Manager + Let's
Encrypt), Tailscale as the mesh tunnel between edge and home. Cloudflare
DNS (DNS-only). Cost-benefit was run by four parallel analysis agents
(network / SRE / TCO / migration).

**Why.** Stated honestly in `docs/migration-cloud-run-to-self-hosted.md`:
the *cheapest, safest* move was a Cloudflare Worker in front of Cloud Run.
The migration was a **deliberate skills/portfolio choice** for full-stack
ownership (BGP → Flask), not a cost optimization. The trigger was a
path-stripping Squarespace 302 that broke OAuth callbacks and deep links.

**Result.**
- Apex serves the app directly — no 302, path preserved, canonical URL.
- No cold starts: app is hot 24/7. ~250–300 ms end-to-end from a PL client
  through Hetzner → Tailscale → LXC; ~42 ms measured Tailscale mesh hop.
- Cash cost ~€7.16/mo (Hetzner CX23 €3.99 + IPv4 €0.50 + domain ~€1.67 +
  NUC power ~€1; Tailscale/Cloudflare free).
- Honest trade: realistic SLA 98–99% (home power outage = downtime), ~3–6
  ops hrs/mo. If time is priced at €50/hr, TCO is ~30–70× worse than
  Cloud Run + CF Worker. Recorded as such — the value is learning, not cash.

**Learned.** Document the option you *didn't* take and why. The migration
write-up says outright that this is not the rational cost choice; that
honesty is what makes the rest of the doc trustworthy. Also: WiFi as a
production data plane is an anti-pattern (pull Ethernet first); homelab
Docker host = privileged LXC + AppArmor unconfined is the standard, not a
shortcut; set up a third-party uptime check *before* cutover so the first
alert isn't from the self-monitoring stack that may be down with the house.

## 2026-05 — self-hosted CI/CD: Forgejo Actions + Harbor

**What.** Replaced GitHub Actions (billing-blocked) with a self-hosted
Forgejo Actions runner (the CI runner host on the same NUC) and a Harbor registry.
Pipeline on every merge to `main`:

```
lint (ruff) → test → trivy fs → build + push Harbor (staging tag)
  → trivy image scan → promote (re-tag staging digest as prod, zero rebuild)
  → deploy-staging (ssh the prod host, compose up :8081, smoke)
  → deploy-prod    (ssh the prod host, compose up :8080, smoke,
                    auto-rollback on smoke fail via .env.bak)
```

Plus a monthly `monthly-db-update.yml` cron (`15 19 27 * *`) that pulls
fresh UKE data, rebuilds `stations.db`, commits + pushes via
`FORGEJO_PUSH_TOKEN`; that commit then drives the main pipeline to redeploy
with the new dataset.

**Result.** Promote re-tags the staging digest as prod (build once, deploy
the identical image). SBOM (syft, CycloneDX) + Trivy + pip-audit + bandit
in the chain. The pipeline took real debugging — DinD dropped for the
runner's local Docker, `head` removed from a verify step (SIGPIPE → exit
141 broke the build), Trivy `--skip-dirs` on vendored JS with unfixable
CVEs, node-base container so `actions/checkout` works.

**Learned.** "Build once, promote the digest" is the cheap way to guarantee
staging and prod run the same bytes. Most CI time went into environment
quirks (SIGPIPE, base-image node, Alpine vs apt), not the happy path —
budget for that. Per-PR perf gate didn't survive the migration intact
(parked as `.github/workflows/perf.yaml.disabled`); smoke + auto-rollback
did. Recorded as a known gap, not papered over.

## 2026-06-10 — security audit #2 (re-audit + privacy compliance)

**What.** Full re-audit (`docs/security-audit-2026-06-10.md`) plus a
data-logging-vs-privacy-policy compliance pass. Prior fixes were *verified
landed* rather than re-reported.

**Result.**
- Fixed: case-insensitive `is_production` (a lowercase `ENV=production` was
  silently disabling Secure cookies and the SECRET_KEY boot guard — HIGH);
  `hmac.compare_digest` on admin-trigger tokens; compose env-var-name drift;
  limiter `RATELIMIT_STORAGE_URI` knob.
- Privacy mismatches fixed: undeclared map-tile sub-processors (CARTO /
  Esri / OSMF receive map users' IPs), `EmailEvent` retention surviving
  account deletion, undeclared `ss_sid` cookie (scoped to anti-abuse only,
  no analytics), full-email-in-logs, session-cookie-lifetime misstatement.
- Verified clean: SQLi (fully parameterized), XSS (`|safe` only on
  committed static markdown), CSRF coverage, sha256 API keys, KMS-wrapped
  TOTP, stateless single-use reset tokens, ECDSA-verified SendGrid webhook
  (fail-closed).

**Learned.** A re-audit's job is as much to *verify the last audit's fixes
stayed fixed* as to find new bugs. The highest-impact new finding was a
silent config bug (`ENV=production` lowercase), not a crypto flaw — boring
config correctness outranks exotic vulnerabilities.

## 2026-06 — database simplification

**What.** Three refactors that removed guesswork and boot-time magic:
- `data_date` stored in `stations.db` metadata (`f9eaeb1`) — stop inferring
  the dataset date from file mtime; `/stats` "last refresh" now reads it.
- Stats snapshot history moved from a baked `stats_history.jsonl` to a
  `users.db` table (`ad3bf91`, Alembic migration `0003`).
- Dropped the `users.db` seed-from-image at boot (`1fa9c7e`) — Alembic owns
  the schema now; no more create-all-then-patch at startup.

**Why.** mtime is not metadata; JSONL-merged-on-boot is fragile; seeding a
schema from an image is the thing migrations exist to replace.

**Result.** Boot path is simpler and deterministic; each change shipped
with its own integration test (`test_get_data_date`, `test_stats_snapshot`,
`test_boot_users_db_no_seed`). 477 tests green.

**Learned.** When metadata lives in a filename or a boot hook, move it into
the data store and let the migration tool own the schema. Less boot-time
branching, fewer "why is the date wrong" bugs.

## 2026-05 → 06 — UX, i18n, privacy

**What.**
- Answer-first verdict card (`3283167`, `e425384`) — lead with the
  is-this-spot-covered verdict, collapse the legend, native stats-panel
  look. Favicon-matched signal colors, dark-mode legibility.
- No-FOUC theming (`cce4c35`) — apply theme before first paint to kill the
  light↔dark flash.
- i18n PL/EN (`cea4f1c`, `dd4cb3d`, `c26ef99`) — Polish language toggle,
  content pages, /stats, trend chart, JS toasts, reset-password flow.
- GDPR/privacy (`d941288` onward) — `/privacy` Art. 13 transparency notice,
  `/data-deletion` (Art. 17 erasure + Facebook OAuth requirement),
  unsubscribe flow, real sub-processor disclosure, cookie scoping.

**Learned.** Theme-before-paint and answer-first are small diffs with
outsized perceived-quality payoff. GDPR accuracy is a code-vs-policy
reconciliation problem, not a legal-text problem — the audit found the
policy *over-promised* relative to what the code did, in both directions.

---

## What's next

From `docs/ROADMAP.md` (P-priority key: P1 blocks revenue, P2 limits
scaling, P3 nice-to-have):

- **Re-enable the per-PR perf gate on Forgejo CI** — shipped for GitHub
  Actions, parked since the migration; Forgejo covers smoke + auto-rollback
  but not the p95 gate.
- **Shared rate-limiter store** (Redis via `RATELIMIT_STORAGE_URI`) —
  counters are per-worker in-memory today; exact limits across workers,
  survive deploys. (Security audit #2 N2.)
- **Memoise markdown pages** — `/tips` / `/data` render markdown per
  request; ~2 ms median but cold render hits 150–527 ms and dominates every
  snapshot tail. ~5 LOC, mtime-keyed. (P3.)
- **Modularity refactor** — move stations routes to a blueprint, introduce
  a service/repository layer (P2), the lift that unlocks clean multi-tenant.
- **Multi-tenant primitives** — `tenant_id` on `BaseStation`/`User`,
  tenant-scoped queries, per-tenant bounds/providers/rate-limits (P1 once
  there's a paying customer, P3 until then).
