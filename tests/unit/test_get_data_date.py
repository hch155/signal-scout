"""Unit tests for queries.get_data_date — UKE data date resolution."""
import sqlite3

import pytest

pytestmark = pytest.mark.unit

from queries import get_data_date  # noqa: E402


def _make_db(path, with_metadata=True, data_date="2026-05-28"):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE base_station (id INTEGER PRIMARY KEY)")
    if with_metadata:
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO metadata (key, value) VALUES ('data_date', ?)",
            (data_date,),
        )
    conn.commit()
    conn.close()


def test_reads_metadata_when_present(tmp_path):
    db = str(tmp_path / "stations.db")
    _make_db(db, with_metadata=True, data_date="2026-05-28")
    assert get_data_date(db) == "2026-05-28"


def test_falls_back_to_mtime_when_metadata_absent(tmp_path):
    db = str(tmp_path / "stations.db")
    _make_db(db, with_metadata=False)
    # mtime fallback yields a YYYY-MM-DD string (today, in UTC).
    result = get_data_date(db)
    assert result != "unknown"
    assert len(result) == 10 and result[4] == "-" and result[7] == "-"


def test_falls_back_to_mtime_when_metadata_has_no_row(tmp_path):
    db = str(tmp_path / "stations.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    result = get_data_date(db)
    assert len(result) == 10


def test_returns_unknown_when_file_missing(tmp_path):
    assert get_data_date(str(tmp_path / "does-not-exist.db")) == "unknown"
