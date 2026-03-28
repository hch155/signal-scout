# Performance Test Results — SQL GROUP_CONCAT optimization
**Date:** 2026-03-27
**Environment:** macOS (Darwin 25.3.0), Python 3.12.2, Flask dev server, SQLite
**Test:** 100 random requests across 4 endpoint types, no rate limiting
**Script:** `scripts/perf_test.py`

## Change description
Replaced Python-side grouping loop in `find_nearest_stations()` with SQL `GROUP_CONCAT(DISTINCT frequency_band)` + `GROUP BY latitude, longitude`. Added composite index `ix_segment_provider_band` on `(latitude_segment, service_provider, frequency_band)`.

## BEFORE (Python grouping, no composite index)

| Endpoint              | Reqs | Min (ms) | Avg (ms) | Med (ms) | Max (ms) | P95 (ms) |
|-----------------------|------|----------|----------|----------|----------|----------|
| POST /submit_location |   14 |    27.53 |    84.61 |    82.68 |   144.48 |   144.48 |
| GET /stations         |   31 |     8.76 |    32.29 |    19.43 |   112.66 |    98.48 |
| GET /search_stations  |   30 |    11.57 |    18.26 |    12.72 |   170.36 |    22.84 |
| GET /static_pages     |   25 |     2.49 |    70.38 |     5.08 |   197.37 |   192.18 |
| **TOTAL**             |  100 |     2.49 |    44.93 |    13.40 |   197.37 |   185.61 |

## AFTER (SQL GROUP_CONCAT + composite index)

| Endpoint              | Reqs | Min (ms) | Avg (ms) | Med (ms) | Max (ms) | P95 (ms) |
|-----------------------|------|----------|----------|----------|----------|----------|
| POST /submit_location |   30 |     4.95 |    23.95 |    21.62 |    54.20 |    47.97 |
| GET /stations         |   21 |     2.03 |    10.99 |     9.92 |    33.06 |    20.04 |
| GET /search_stations  |   28 |    11.53 |    12.48 |    12.36 |    15.47 |    13.45 |
| GET /static_pages     |   21 |     2.06 |    31.99 |     3.25 |   263.69 |   166.25 |
| **TOTAL**             |  100 |     2.03 |    19.70 |    12.39 |   263.69 |    47.97 |

## Summary

| Endpoint              | Avg change | Med change | P95 change |
|-----------------------|------------|------------|------------|
| POST /submit_location |       -72% |       -74% |       -67% |
| GET /stations         |       -66% |       -49% |       -80% |
| GET /search_stations  |       -32% |        -3% |       -41% |
| TOTAL                 |       -56% |        -8% |       -74% |

## Notes
- `search_stations` improvement is minimal — it uses `LIKE` query, not the changed `find_nearest_stations` function
- `static_pages` variance is high due to template rendering / markdown parsing, unrelated to this change
- The key endpoints (`submit_location`, `stations`) show 49-80% median improvement
- Frequency band filtering verified: subset check in app.py still works correctly with GROUP_CONCAT

## Bug found during review
Original Python code grouped by `(latitude, longitude)` which merged different operators sharing the same mast into one station (10 locations affected, e.g. P4 + TOPR in Zakopane). Fixed by grouping by `(latitude, longitude, service_provider)` — both in old Python code and new SQL query. This is a **pre-existing bug** that was also present before this optimization.
