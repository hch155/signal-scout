# Performance snapshot — 2026-05-09 (post CI unblock)

Environment: localhost macOS, gunicorn workers=1, prod stations DB (~38 MB / 188k rows), Python 3.12.13.

## Test 1 — `scripts/perf_test.py` (random-endpoint distribution)

```
PYTHONPATH=src STATIONS_DB_PATH=src/instance/stations.db USERS_DB_PATH=.perf_users.db \
  SECRET_KEY=perf-local DEFAULT_RATE_LIMIT="10000 per minute" \
  venv/bin/gunicorn --workers=1 --timeout=30 --bind=127.0.0.1:8089 src.app:app &
venv/bin/python scripts/perf_test.py http://127.0.0.1:8089
```

100 requests, mixed endpoints, single client.

| Endpoint                | Reqs | Err | Min (ms) | Avg (ms) | Med (ms) | Max (ms) | P95 (ms) |
|-------------------------|-----:|----:|---------:|---------:|---------:|---------:|---------:|
| POST /submit_location   |   27 |   0 |     6.81 |    22.71 |    22.30 |    66.51 |    49.72 |
| GET /stations           |   26 |   0 |     1.77 |    13.12 |     9.75 |    45.36 |    43.90 |
| GET /search_stations    |   29 |   0 |    12.03 |    19.44 |    12.81 |   184.37 |    27.64 |
| GET /static_pages       |   18 |   0 |     1.50 |   111.24 |     2.04 |   527.32 |   527.32 |
| **TOTAL**               |  100 |   0 |     1.50 |    35.20 |    13.26 |   527.32 |   184.37 |

## Test 2 — perf.yaml inline harness (100 GETs to `/`)

Same gunicorn instance, same env. Mirrors what `.github/workflows/perf.yaml` runs.

```
{
  "endpoint": "/",
  "n_requests": 100,
  "n_success": 100,
  "n_errors": 0,
  "min_ms": 0.64,
  "p50_ms": 0.79,
  "p95_ms": 1.01,
  "p99_ms": 1.39,
  "max_ms": 1.82,
  "mean_ms": 0.82,
  "budget_p95_ms": 500
}
```

p95 = 1.01 ms vs budget 500 ms — **massive headroom** because `/` is a static template render with no DB hit.

## Notes

- All POST/GET endpoints under their respective rate limits **without** the `DEFAULT_RATE_LIMIT` override; the override only matters for the synthetic 100-in-a-row test.
- Static-page tail (max 527 ms on /static_pages) is one cold markdown render of /tips or /data — first request, JIT-style cost. Median is 2 ms.
- Compared to 2026-04-22 baseline: POST /submit_location avg moved 19.5 → 22.7 ms (+16%), still well within budget; likely audit-event write overhead added in PR #46+.
- p95 of compound test (random distribution) = 184 ms, far from 500 ms perf.yaml budget.

## CI fixes shipped in this run

- `src/app.py`: `default_limits` now reads from `DEFAULT_RATE_LIMIT` env (perf.yaml sets it to 10000/min so the inline harness doesn't trip rate limit on 100 sequential `/` GETs).
- `.github/workflows/perf.yaml`: added env override.
- `tests/requirements-test.txt`: pytest pinned `>=8.4,<9` (pytest-playwright 0.7.1 caps at <9; CI install was failing).
- `src/api_access.py`: `hashlib.sha1(..., usedforsecurity=False)` to silence bandit B324 false-positive (deterministic ID→coords map, not crypto).
- `src/observability.py`: `from collections import OrderedDict` (was forward-ref string only — ruff F821 was blocking lint).
- `tests/unit/test_audit_ip_redaction.py`: lazy-import `_redact_ip` so module-level import doesn't drag `app` at pytest collection (was caching the wrong stations DB and breaking integration tests).

Full local suite **342/342 green**.
