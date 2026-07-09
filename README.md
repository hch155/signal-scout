# Signal-Scout

[signal-scout.com](https://www.signal-scout.com) — find the nearest cellular
base stations across Poland by operator, frequency band, and distance, and
position your equipment for the best possible signal.

## Features

- Interactive map of base stations around any point in Poland
- Filter by operator (Play, Orange, T-Mobile, Plus) and frequency band
- Distance-based signal tiers and per-band coverage
- Accounts with saved locations and coverage-gap email alerts
- Polish / English UI

## Tech stack

Python · Flask · SQLAlchemy · SQLite · gunicorn · Leaflet · Tailwind, on a
self-hosted CI/CD pipeline (Forgejo Actions → Harbor → Portainer), ~€7/month.

## Performance

The hot path (`GET /stations`) was rebuilt from Python-side row grouping to a
single SQL `GROUP_CONCAT` query plus a composite index — p95 **98 ms → 20 ms**,
with the 100-request mixed-endpoint benchmark falling **185.6 ms → 48.0 ms (−74%)**
on the 188k-row production dataset. Benchmarks are committed under `tests/results/`.

## Quick start

```bash
git clone https://github.com/hch155/signal-scout.git
cd signal-scout
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd src && python app.py          # http://localhost:8080
```

Or: `docker build -t signal-scout . && docker run -p 8080:8080 signal-scout`

## Caveats

- **Data** comes from the public UKE radio-permit registry — a point-in-time
  snapshot. The ingestion/parsing pipeline is maintained separately and is not
  part of this repository (the built `stations.db` ships so the app runs).
- **Coverage is modelled, not measured** — signal tiers derive from transmitter
  location and distance (RF path-loss), not field measurements; treat them as an
  estimate, not a guarantee.
- **Poland only**, limited to operators/bands present in the UKE registry.
- This is a public mirror; some infrastructure/ops files are omitted.

## Contact

hcylwik@gmail.com
