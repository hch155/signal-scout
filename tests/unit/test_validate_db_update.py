"""Unit tests for scripts/validate_db_update — download + database validators.

Drives validate_downloads(data_dir=...) and validate_database(previous_count,
db_path=...) against synthetic temp xlsx fixtures and temp sqlite DBs.
"""
import os
import sqlite3
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

pytestmark = pytest.mark.unit

import validate_db_update as vdb  # noqa: E402

BANDS = vdb.EXPECTED_BANDS


def _make_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE base_station "
        "(basestation_id TEXT, frequency_band TEXT, latitude REAL, longitude REAL)"
    )
    conn.executemany(
        "INSERT INTO base_station "
        "(basestation_id, frequency_band, latitude, longitude) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _good_rows(total, bands=BANDS):
    return [
        (f"ST{i}", bands[i % len(bands)].upper(), 52.0, 20.0)
        for i in range(total)
    ]


def _make_downloads(data_dir, bands=BANDS, size=2048):
    data_dir.mkdir()
    for band in bands:
        (data_dir / f"{band}.xlsx").write_bytes(b"x" * size)


def test_count_drop_over_25pct_is_error(tmp_path):
    db = tmp_path / "stations.db"
    _make_db(db, _good_rows(700))
    errors, _ = vdb.validate_database(previous_count=1000, db_path=str(db))
    assert errors
    assert any("dropped" in e for e in errors)


def test_count_drop_5_to_25pct_is_warning_not_error(tmp_path):
    db = tmp_path / "stations.db"
    _make_db(db, _good_rows(900))
    errors, warnings = vdb.validate_database(previous_count=1000, db_path=str(db))
    assert errors == []
    assert any("decreased" in w for w in warnings)


def test_missing_band_is_error(tmp_path):
    db = tmp_path / "stations.db"
    bands = [b for b in BANDS if b != "5g700"]
    rows = _good_rows(len(bands) * 20, bands=bands)
    _make_db(db, rows)
    errors, _ = vdb.validate_database(previous_count=len(rows), db_path=str(db))
    assert any("Missing frequency band in DB: 5G700" in e for e in errors)


def test_out_of_bounds_coords_is_error(tmp_path):
    db = tmp_path / "stations.db"
    good = _good_rows(280)
    oob = [
        ("OOB0", "LTE800", 60.0, 20.0),
        ("OOB1", "LTE800", 52.0, 30.0),
        ("OOB2", "LTE800", 60.0, 30.0),
    ]
    _make_db(db, good + oob)
    errors, _ = vdb.validate_database(
        previous_count=len(good) + len(oob), db_path=str(db)
    )
    assert any("3 records have coordinates outside Polish bounds" in e for e in errors)


def test_duplicate_station_band_is_error(tmp_path):
    db = tmp_path / "stations.db"
    good = _good_rows(280)
    dupes = [
        ("DUP", "LTE800", 52.0, 20.0),
        ("DUP", "LTE800", 52.0, 20.0),
    ]
    _make_db(db, good + dupes)
    errors, _ = vdb.validate_database(
        previous_count=len(good) + len(dupes), db_path=str(db)
    )
    assert any("duplicate (station, band)" in e for e in errors)


def test_suspiciously_small_xlsx_is_download_error(tmp_path):
    data_dir = tmp_path / "downloads"
    _make_downloads(data_dir)
    (data_dir / f"{BANDS[0]}.xlsx").write_bytes(b"x" * 100)
    errors = vdb.validate_downloads(data_dir=str(data_dir))
    assert any("File suspiciously small" in e for e in errors)


def test_missing_xlsx_for_a_band_is_download_error(tmp_path):
    data_dir = tmp_path / "downloads"
    _make_downloads(data_dir, bands=[b for b in BANDS if b != "5g700"])
    errors = vdb.validate_downloads(data_dir=str(data_dir))
    assert any("Missing file for band: 5g700" in e for e in errors)
    assert any("Expected at least 14 Excel files" in e for e in errors)


def test_healthy_update_passes_both_steps(tmp_path):
    data_dir = tmp_path / "downloads"
    _make_downloads(data_dir)
    assert vdb.validate_downloads(data_dir=str(data_dir)) == []

    db = tmp_path / "stations.db"
    _make_db(db, _good_rows(1010))
    errors, warnings = vdb.validate_database(previous_count=1000, db_path=str(db))
    assert errors == []
    assert warnings == []
