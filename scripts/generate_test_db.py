#!/usr/bin/env python3
"""
Generate a deterministic miniature stations DB for tests.

Output: tests/fixtures/test_stations.db
Mirrors the production schema (src/models.py BaseStation) and the
ix_segment_provider_band composite index used by find_nearest_stations().

Coverage:
- 3 latitude bands (Warszawa ~52.23, Kraków ~50.06, Gdańsk ~54.35) so
  segment partitioning logic is exercised
- All 4 major Polish providers
- All current frequency bands (5G/LTE/UMTS/GSM)
- A handful of physically co-located rows (same lat/lng/provider, multiple
  bands) so the GROUP_CONCAT path in find_nearest_stations is exercised
- One adversarial row with a script-tag provider name, to assert that
  XSS-defense renders it safely (used by tests/e2e/test_xss_defense.py)
"""

from __future__ import annotations

import os
import sqlite3
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_PATH = os.path.join(ROOT, "tests", "fixtures", "test_stations.db")
SEGMENT_BASE_LAT = 49.0
SEGMENT_SIZE = 0.1


def latitude_segment(lat: float) -> int:
    return int((lat - SEGMENT_BASE_LAT) / SEGMENT_SIZE)


PROVIDERS = [
    "Orange Polska S.A.",
    "P4 sp. z o.o.",
    "Polkomtel sp. z o.o.",
    "T-Mobile Polska S.A.",
]

BANDS_5G = ["5G3600", "5G2100", "5G1800", "5G700"]
BANDS_LTE = ["LTE2600", "LTE2100", "LTE1800", "LTE900", "LTE800", "LTE700"]
BANDS_UMTS = ["UMTS2100", "UMTS900"]
BANDS_GSM = ["GSM1800", "GSM900"]
ALL_BANDS = BANDS_5G + BANDS_LTE + BANDS_UMTS + BANDS_GSM

# (city, lat, lng) hubs in 3 different latitude segments
HUBS = [
    ("Warszawa", 52.2297, 21.0122),
    ("Kraków",   50.0647, 19.9450),
    ("Gdańsk",   54.3520, 18.6466),
]

SCHEMA_SQL = """
CREATE TABLE base_station (
    id INTEGER NOT NULL,
    basestation_id VARCHAR,
    city VARCHAR,
    location VARCHAR,
    service_provider VARCHAR,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    frequency_band VARCHAR NOT NULL,
    rat VARCHAR,
    frequency_band_count INTEGER,
    latitude_segment INTEGER,
    PRIMARY KEY (id)
);
CREATE INDEX ix_base_station_latitude ON base_station(latitude);
CREATE INDEX ix_base_station_longitude ON base_station(longitude);
CREATE INDEX ix_base_station_frequency_band ON base_station(frequency_band);
CREATE INDEX ix_base_station_latitude_segment ON base_station(latitude_segment);
CREATE INDEX ix_segment_provider_band ON base_station(latitude_segment, service_provider, frequency_band);
"""


def build_rows():
    rows = []
    next_id = 1
    bts_seq = 1000

    for hub_idx, (city, base_lat, base_lng) in enumerate(HUBS):
        for prov_idx, provider in enumerate(PROVIDERS):
            # Two physical sites per provider per hub, each with several bands
            for site_idx in range(2):
                # Small deterministic offset so each site is distinct
                lat = round(base_lat + 0.001 * (prov_idx + 1) + 0.0005 * site_idx, 6)
                lng = round(base_lng + 0.001 * (prov_idx + 1) + 0.0005 * site_idx, 6)
                bts_id = f"T{bts_seq:04d}"
                bts_seq += 1
                # Provider 0 gets full band stack; rest get a slice — keeps test
                # data small but lets filter combinations have ≥1 hit.
                if prov_idx == 0:
                    bands = ALL_BANDS
                elif prov_idx == 1:
                    bands = BANDS_5G + BANDS_LTE
                elif prov_idx == 2:
                    bands = BANDS_LTE + BANDS_UMTS + BANDS_GSM
                else:
                    bands = ["5G2100", "LTE1800", "LTE800", "GSM900"]

                for band in bands:
                    rows.append((
                        next_id,
                        bts_id,
                        city,
                        f"site-{hub_idx}-{prov_idx}-{site_idx}",
                        provider,
                        lat,
                        lng,
                        band,
                        None,                          # rat
                        len(bands),                    # frequency_band_count
                        latitude_segment(lat),
                    ))
                    next_id += 1

    # Adversarial row (XSS regression). Stays in Warszawa segment.
    xss_lat = 52.2300
    xss_lng = 21.0125
    rows.append((
        next_id,
        "T9999",
        "<img src=x onerror=window.__pwned=1>",     # malicious city
        "<script>window.__pwned=1</script>",         # malicious location
        '"><script>alert(1)</script>',               # malicious provider
        xss_lat,
        xss_lng,
        "LTE1800",
        None,
        1,
        latitude_segment(xss_lat),
    ))
    return rows


def main() -> int:
    fixtures_dir = os.path.dirname(OUT_PATH)
    os.makedirs(fixtures_dir, exist_ok=True)
    if os.path.exists(OUT_PATH):
        os.remove(OUT_PATH)

    conn = sqlite3.connect(OUT_PATH)
    try:
        conn.executescript(SCHEMA_SQL)
        rows = build_rows()
        conn.executemany(
            "INSERT INTO base_station "
            "(id, basestation_id, city, location, service_provider, "
            " latitude, longitude, frequency_band, rat, "
            " frequency_band_count, latitude_segment) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        print(f"Wrote {len(rows)} rows to {OUT_PATH}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
