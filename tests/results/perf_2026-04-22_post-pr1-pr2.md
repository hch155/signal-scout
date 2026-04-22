# Performance snapshot — 2026-04-22 (post PR #1 + PR #2)

Environment: localhost (Werkzeug dev server), Python 3.12.13, fixture stations DB (229 rows / 3 hubs).

Command:
```
python src/app.py &        # ENV unset → debug-friendly cookie config
python scripts/perf_test.py http://127.0.0.1:8080
```

100 requests, random endpoint distribution. CSRF token fetched once via meta tag and reused.

| Endpoint                | Reqs | Err | Min (ms) | Avg (ms) | Med (ms) | Max (ms) | P95 (ms) |
|-------------------------|-----:|----:|---------:|---------:|---------:|---------:|---------:|
| POST /submit_location   |   18 |   0 |     3.77 |    19.51 |    18.65 |    44.65 |    44.65 |
| GET /stations           |   24 |   0 |     1.74 |    12.60 |    11.53 |    25.80 |    25.11 |
| GET /search_stations    |   22 |   0 |    10.55 |    11.34 |    11.18 |    12.35 |    12.35 |
| GET /static_pages       |   36 |   0 |     1.28 |    35.00 |     2.31 |   150.88 |   150.53 |
| **TOTAL**               |  100 |   0 |     1.28 |    21.63 |    11.06 |   150.88 |   147.95 |

Notes:
- Zero errors — confirms PR #1 CSRF flow works end-to-end (POST /submit_location now requires the token via header).
- P95 latency well within usable bounds for a public-facing app.
- Static-page tail (P95 ~150 ms) dominated by markdown render of /tips and /data on every request — not memoised; flagged in `docs/ROADMAP.md` for future caching.
- Comparison points: prior baseline `tests/results/perf_2026-03-27_sql_grouping.md` reflects pre-PR #1 era and used a 188k-row prod DB, so latency numbers are not directly comparable.
