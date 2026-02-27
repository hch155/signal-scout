"""Validate database update steps.

Usage:
  python scripts/validate_db_update.py --step downloads
  python scripts/validate_db_update.py --step database --previous-count 223305
"""
import argparse
import glob
import os
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_STATION_DATA_DIR = os.path.join(SCRIPT_DIR, '..', 'base_station_data')
DB_PATH = os.path.join(SCRIPT_DIR, '..', 'src', 'instance', 'stations.db')

EXPECTED_BANDS = [
    '5g3600', '5g2100', '5g1800', '5g700',
    'lte2600', 'lte2100', 'lte1800', 'lte900', 'lte800', 'lte700',
    'umts2100', 'umts900',
    'gsm900', 'gsm1800',
]

# Polish geographical bounds (with margin)
LAT_MIN, LAT_MAX = 49.0, 55.5
LON_MIN, LON_MAX = 14.0, 24.2

# Maximum allowed percentage drop in record count
MAX_DROP_PERCENT = 5.0
WARN_DROP_PERCENT = 1.0


def validate_downloads():
    """Validate that all expected Excel files were downloaded."""
    errors = []

    xlsx_files = glob.glob(os.path.join(BASE_STATION_DATA_DIR, '*.xlsx'))
    print(f'Found {len(xlsx_files)} Excel files')

    if len(xlsx_files) < len(EXPECTED_BANDS):
        errors.append(f'Expected at least {len(EXPECTED_BANDS)} Excel files, found {len(xlsx_files)}')

    for band in EXPECTED_BANDS:
        matching = [f for f in xlsx_files if band in os.path.basename(f).lower()]
        if not matching:
            errors.append(f'Missing file for band: {band}')
        else:
            print(f'  {band}: {os.path.basename(matching[0])}')

    for f in xlsx_files:
        size = os.path.getsize(f)
        if size < 1024:
            errors.append(f'File suspiciously small ({size} bytes): {os.path.basename(f)}')

    return errors


def validate_database(previous_count):
    """Validate the rebuilt database."""
    errors = []
    warnings = []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Total record count
    new_count = cursor.execute('SELECT COUNT(*) FROM base_station').fetchone()[0]
    print(f'Record count: {previous_count} -> {new_count}')

    if previous_count > 0:
        change_pct = ((new_count - previous_count) / previous_count) * 100
        drop_pct = -change_pct if change_pct < 0 else 0

        if drop_pct > MAX_DROP_PERCENT:
            errors.append(
                f'Record count dropped {drop_pct:.1f}%: {previous_count} -> {new_count}'
            )
        elif drop_pct > WARN_DROP_PERCENT:
            warnings.append(
                f'Record count decreased {drop_pct:.1f}%: {previous_count} -> {new_count}'
            )
        else:
            print(f'  Change: {change_pct:+.1f}%')

    # 2. Duplicate check
    dupes = cursor.execute('''
        SELECT basestation_id, frequency_band, COUNT(*) as cnt
        FROM base_station
        GROUP BY basestation_id, frequency_band
        HAVING cnt > 1
        LIMIT 10
    ''').fetchall()
    if dupes:
        errors.append(
            f'Found {len(dupes)}+ duplicate (station, band) pairs. '
            f'First 3: {dupes[:3]}'
        )
    else:
        print('  No duplicates found')

    # 3. Coordinate sanity
    out_of_bounds = cursor.execute(
        'SELECT COUNT(*) FROM base_station '
        'WHERE latitude < ? OR latitude > ? OR longitude < ? OR longitude > ?',
        (LAT_MIN, LAT_MAX, LON_MIN, LON_MAX)
    ).fetchone()[0]
    if out_of_bounds > 0:
        errors.append(f'{out_of_bounds} records have coordinates outside Polish bounds')
    else:
        print('  All coordinates within Polish bounds')

    # 4. Band completeness
    db_bands = [
        row[0].lower() for row in
        cursor.execute('SELECT DISTINCT frequency_band FROM base_station').fetchall()
    ]
    for band in EXPECTED_BANDS:
        if band not in db_bands:
            errors.append(f'Missing frequency band in DB: {band.upper()}')
    print(f'  Bands in DB: {len(db_bands)}')

    # 5. Per-band counts
    band_counts = cursor.execute(
        'SELECT frequency_band, COUNT(*) FROM base_station GROUP BY frequency_band'
    ).fetchall()
    for band, count in band_counts:
        if count < 10:
            warnings.append(f'Very low count for {band}: {count} records')
        print(f'    {band}: {count}')

    conn.close()
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description='Validate database update')
    parser.add_argument('--step', required=True, choices=['downloads', 'database'])
    parser.add_argument('--previous-count', type=int, default=0)
    args = parser.parse_args()

    if args.step == 'downloads':
        errors = validate_downloads()
        if errors:
            print('\nDOWNLOAD VALIDATION FAILED:')
            for e in errors:
                print(f'  - {e}')
            sys.exit(1)
        print('\nDownload validation passed.')

    elif args.step == 'database':
        errors, warnings = validate_database(args.previous_count)
        for w in warnings:
            print(f'WARNING: {w}')
        if errors:
            print('\nDATABASE VALIDATION FAILED:')
            for e in errors:
                print(f'  - {e}')
            sys.exit(1)
        print('\nDatabase validation passed.')


if __name__ == '__main__':
    main()
