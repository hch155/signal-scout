"""stats_snapshot table: backfill, dedup, idempotency, and the
table-based read/write API that replaced stats_history.jsonl."""
import json

import pytest


@pytest.fixture(autouse=True)
def _clean_snapshots(app):
    """Each test starts from an empty stats_snapshot table (boot backfill
    seeds it, and other tests may have written rows)."""
    from database import db
    from models import StatsSnapshot
    with app.app_context():
        db.session.query(StatsSnapshot).delete()
        db.session.commit()
    yield
    with app.app_context():
        db.session.query(StatsSnapshot).delete()
        db.session.commit()


def _stats(sites, entries):
    return {
        'physical_sites': {'P4': sites},
        'sites_per_generation': {},
        'provider_totals': {'P4': sites},
        'generation_breakdown': {},
        'generation_totals': {'5G': entries},
        'grand_total_sites': sites,
        'grand_total_entries': entries,
    }


def test_write_and_read_roundtrip(app):
    from stats_history import (
        maybe_write_snapshot, read_history, previous_snapshot,
    )
    with app.app_context():
        assert maybe_write_snapshot(None, '2026-04-25', _stats(100, 200)) is True
        assert maybe_write_snapshot(None, '2026-05-25', _stats(110, 220)) is True
        # Duplicate key is a no-op.
        assert maybe_write_snapshot(None, '2026-05-25', _stats(999, 999)) is False

        rows = read_history(None)
        assert [r['snapshot_key'] for r in rows] == ['2026-04-25', '2026-05-25']
        assert rows[0]['grand_total_sites'] == 100
        assert rows[1]['generation_totals'] == {'5G': 220}

        prev = previous_snapshot(None, '2026-05-25')
        assert prev['snapshot_key'] == '2026-04-25'
        assert previous_snapshot(None, '2026-04-25') is None


def test_read_history_limit(app):
    from stats_history import maybe_write_snapshot, read_history
    with app.app_context():
        for d in ('2026-01-25', '2026-02-25', '2026-03-25'):
            maybe_write_snapshot(None, d, _stats(1, 1))
        rows = read_history(None, limit=2)
        assert [r['snapshot_key'] for r in rows] == ['2026-02-25', '2026-03-25']


def _write_jsonl(path, rows):
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')


def test_backfill_imports_rows_and_dedups(app, tmp_path):
    from stats_history import backfill_from_jsonl_if_empty, read_history
    jsonl = tmp_path / "stats_history.jsonl"
    _write_jsonl(jsonl, [
        {'recorded_at': '2026-01-25T00:00:00Z', 'grand_total_sites': 1,
         'grand_total_entries': 10},
        {'recorded_at': '2026-02-25T00:00:00Z', 'grand_total_sites': 2,
         'grand_total_entries': 20},
        # Same date prefix as the first → deduped on snapshot_key.
        {'recorded_at': '2026-01-25T12:00:00Z', 'grand_total_sites': 99,
         'grand_total_entries': 99},
        # No recorded_at: derive key from db_mtime (2026-03-25 UTC).
        {'db_mtime': 1774396800.0, 'grand_total_sites': 3,
         'grand_total_entries': 30},
    ])
    with app.app_context():
        n = backfill_from_jsonl_if_empty(None, str(jsonl))
        assert n == 3
        rows = read_history(None)
        keys = [r['snapshot_key'] for r in rows]
        assert keys == ['2026-01-25', '2026-02-25', '2026-03-25']
        # First-seen wins for the deduped 2026-01-25 key.
        assert rows[0]['grand_total_sites'] == 1


def test_backfill_is_idempotent(app, tmp_path):
    from stats_history import backfill_from_jsonl_if_empty, read_history
    jsonl = tmp_path / "stats_history.jsonl"
    _write_jsonl(jsonl, [
        {'recorded_at': '2026-01-25T00:00:00Z', 'grand_total_sites': 1,
         'grand_total_entries': 10},
        {'recorded_at': '2026-02-25T00:00:00Z', 'grand_total_sites': 2,
         'grand_total_entries': 20},
    ])
    with app.app_context():
        assert backfill_from_jsonl_if_empty(None, str(jsonl)) == 2
        # Second run short-circuits because the table is non-empty.
        assert backfill_from_jsonl_if_empty(None, str(jsonl)) == 0
        assert len(read_history(None)) == 2


def test_backfill_preserves_all_distinct_keys(app, tmp_path):
    """Data-preservation invariant: every distinct date in the JSONL ends
    up as a snapshot_key in the table (no historical snapshot lost)."""
    from stats_history import backfill_from_jsonl_if_empty, read_history
    # N distinct months plus one same-day duplicate that must collapse.
    src_rows = []
    expected = set()
    for month in range(1, 13):
        key = f"2025-{month:02d}-25"
        expected.add(key)
        src_rows.append({'recorded_at': f"{key}T00:00:00Z",
                         'grand_total_sites': month,
                         'grand_total_entries': month * 10})
    src_rows.append({'recorded_at': "2025-06-25T18:00:00Z",
                     'grand_total_sites': 999, 'grand_total_entries': 999})
    jsonl = tmp_path / "stats_history.jsonl"
    _write_jsonl(jsonl, src_rows)
    with app.app_context():
        backfill_from_jsonl_if_empty(None, str(jsonl))
        got = {r['snapshot_key'] for r in read_history(None)}
        assert got == expected
        assert len(got) == 12


def test_backfill_reads_baked_committed_jsonl(app):
    """The committed src/instance/stats_history.jsonl imports cleanly with
    no lost rows — matches the prod backfill source."""
    import os
    from stats_history import backfill_from_jsonl_if_empty, read_history
    baked = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'src', 'instance', 'stats_history.jsonl',
    )
    # Count distinct date keys in the file.
    expected = set()
    with open(baked, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            ra = r.get('recorded_at')
            if ra:
                expected.add(ra[:10])
    with app.app_context():
        n = backfill_from_jsonl_if_empty(None, baked)
        assert n == len(expected)
        assert {r['snapshot_key'] for r in read_history(None)} == expected
