#!/usr/bin/env python3
"""Generate N random SavedLocation rows inside Poland's bounding box.

Used to seed test data ahead of a UKE refresh: with 50 random spots
in a real account, the next monthly refresh + coverage_alert_run.py
gives a real-world sample of what alerts look like.

Output: JSON file ready for `import_locations_for_user.py` (or any
other importer). Each entry has the same shape POST /account/locations
expects:

    {"name": str, "lat": float, "lng": float,
     "radius_km": float, "alerting_enabled": bool}

Usage:
  python scripts/generate_random_locations.py --count 50 --out fixtures/random_pl_locations.json [--seed 42]
"""
from __future__ import annotations

import argparse
import json
import os
import random
from datetime import datetime

# Same bounds queries.py uses to consider a point "in PL".
PL_LAT_MIN, PL_LAT_MAX = 49.0, 55.5
PL_LNG_MIN, PL_LNG_MAX = 14.0, 24.2


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--count', type=int, default=50)
    ap.add_argument('--out', default='tests/fixtures/random_pl_locations.json')
    ap.add_argument('--seed', type=int, default=None,
                    help="Seed RNG for reproducibility. Default: time-based.")
    ap.add_argument('--radius-km', type=float, default=15.0)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    locations = []
    for i in range(1, args.count + 1):
        lat = round(random.uniform(PL_LAT_MIN, PL_LAT_MAX), 5)
        lng = round(random.uniform(PL_LNG_MIN, PL_LNG_MAX), 5)
        locations.append({
            'name': f'Test spot {i:03d}',
            'lat': lat,
            'lng': lng,
            'radius_km': args.radius_km,
            'alerting_enabled': True,
        })

    payload = {
        'generated_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
        'seed': args.seed,
        'count': args.count,
        'bounds': {
            'lat_min': PL_LAT_MIN, 'lat_max': PL_LAT_MAX,
            'lng_min': PL_LNG_MIN, 'lng_max': PL_LNG_MAX,
        },
        'locations': locations,
    }

    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {len(locations)} locations to {out_path}")


if __name__ == '__main__':
    main()
