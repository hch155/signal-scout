# Signal-Scout

[Signal-Scout](https://www.signal-scout.com) helps you find the nearest
cellular base stations across Poland — by operator, frequency band, and
distance — so you can position equipment for the best possible signal.

## Features

- Interactive map of base stations around any point in Poland
- Filter by operator (Play, Orange, T-Mobile, Plus) and frequency band
- Distance-based signal-strength rings and per-band coverage
- Accounts with saved locations and coverage-gap email alerts
- Polish / English UI

## Performance

The hot path (`GET /stations`, `POST /submit_location`) was rebuilt from
Python-side row grouping to a single SQL `GROUP_CONCAT` query plus a
composite index:

| Endpoint | Before | After |
|---|---|---|
| `/stations` p95 | 185.6 ms | **48.0 ms** (−74%) |
| `POST /submit_location` | 85 ms | **24 ms** (−72%) |

Measured on the production-size dataset (188k rows). Every run is committed
under `tests/results/perf_*.md` with environment and dataset size recorded.

## Tech stack

Python · Flask · SQLAlchemy · SQLite · gunicorn · Leaflet · Tailwind.

In production, a request flows browser → public edge proxy (TLS) → encrypted
tunnel → self-hosted backend, so most of the ~250–300 ms you see end-to-end
is that network hop — run it locally and there's no hop, so responses are
single-digit milliseconds. Infrastructure runs at €7.16/month.

## Data

Base-station data is derived from the public UKE radio-permit registry.
The repository ships the finished `stations.db`; the ingestion/parsing
pipeline is maintained separately and not included here.

## Local development

```bash
git clone https://github.com/hch155/signal-scout.git
cd signal-scout
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd src && python app.py
```

Open http://localhost:8080.

## Docker

```bash
docker build -t signal-scout .
docker run -e ENV=PRODUCTION -p 8080:8080 signal-scout
```

## Tests

```bash
pip install -r tests/requirements-test.txt
pytest
```

48 test files across unit, integration, and end-to-end (Playwright) suites.

## Contact

Questions or suggestions: hcylwik@gmail.com
