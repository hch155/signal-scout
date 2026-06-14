"""Stats snapshot history, stored in the users.db `stats_snapshot` table.

Each monthly UKE refresh, the /stats handler records a snapshot of the
aggregates here. The page then reads the previous snapshot and renders
month-over-month deltas next to the current numbers.

History used to live in a JSONL file merged on boot; it now lives in a
table on the users bind (created by Alembic migration 0003), so it shares
the same persistent mount as the rest of the user data with no bespoke
dedup. `snapshot_key` is the UKE data date (YYYY-MM-DD) — it sorts
chronologically as a string and is UNIQUE, so re-recording the same
refresh is a no-op.

`backfill_from_jsonl_if_empty` is a one-time import path: on first boot
after the migration, the historical snapshots baked into
src/instance/stats_history.jsonl (and any live JSONL next to the prod
users.db) are imported so the trend chart isn't reset to a single point.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from database import db
from models import StatsSnapshot

logger = logging.getLogger(__name__)

_STAT_FIELDS = (
    'physical_sites',
    'sites_per_generation',
    'provider_totals',
    'generation_breakdown',
    'generation_totals',
    'grand_total_sites',
    'grand_total_entries',
)


def _row_to_dict(row: StatsSnapshot) -> dict:
    """Flatten a StatsSnapshot row into the dict shape callers expect:
    the deserialized payload fields plus snapshot_key + recorded_at."""
    try:
        payload = json.loads(row.payload) if row.payload else {}
    except json.JSONDecodeError:
        logger.warning("corrupt payload for snapshot_key=%s", row.snapshot_key)
        payload = {}
    payload['snapshot_key'] = row.snapshot_key
    payload['recorded_at'] = row.recorded_at
    return payload


def read_history(users_db_path: Optional[str] = None,
                 limit: Optional[int] = None) -> list[dict]:
    """Return all snapshots, oldest first (snapshot_key ascending sorts
    chronologically). Optionally cap to the last N."""
    rows = (StatsSnapshot.query
            .order_by(StatsSnapshot.snapshot_key.asc())
            .all())
    out = [_row_to_dict(r) for r in rows]
    if limit is not None:
        out = out[-limit:]
    return out


def previous_snapshot(users_db_path: Optional[str],
                      current_key: str) -> Optional[dict]:
    """Latest snapshot strictly older than current_key (used by /stats for
    MoM deltas). None when there's no prior snapshot."""
    if not current_key:
        return None
    row = (StatsSnapshot.query
           .filter(StatsSnapshot.snapshot_key < current_key)
           .order_by(StatsSnapshot.snapshot_key.desc())
           .first())
    return _row_to_dict(row) if row else None


def maybe_write_snapshot(users_db_path: Optional[str], data_date: str,
                          stats: dict,
                          recorded_at_override: Optional[str] = None) -> bool:
    """Insert a snapshot keyed on data_date if none exists for that key yet.
    Returns True iff a new row was inserted.

    `recorded_at_override` lets backfill stamp the snapshot with the date
    the data refers to; live runs pass None and get utcnow()."""
    if not data_date:
        return False
    exists = (StatsSnapshot.query
              .filter_by(snapshot_key=data_date)
              .first())
    if exists is not None:
        return False
    payload = {field: stats.get(field, {} if field not in
                                ('grand_total_sites', 'grand_total_entries')
                                else 0)
               for field in _STAT_FIELDS}
    recorded_at = recorded_at_override or (datetime.utcnow().isoformat() + 'Z')
    db.session.add(StatsSnapshot(
        snapshot_key=data_date,
        recorded_at=recorded_at,
        payload=json.dumps(payload),
    ))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        # Lost a race to another worker writing the same key — that's fine,
        # the row exists now, so treat as "not inserted by us".
        logger.info("snapshot for %s already written by a concurrent worker",
                    data_date)
        return False
    logger.info("Recorded stats snapshot for %s", data_date)
    return True


def _key_for_jsonl_row(row: dict) -> Optional[str]:
    """Derive a YYYY-MM-DD snapshot_key from a legacy JSONL row."""
    ra = row.get('recorded_at')
    if isinstance(ra, str) and len(ra) >= 10:
        return ra[:10]
    m = row.get('db_mtime')
    if isinstance(m, (int, float)) and m:
        return datetime.utcfromtimestamp(float(m)).strftime('%Y-%m-%d')
    return None


def backfill_from_jsonl_if_empty(users_db_path: Optional[str],
                                 baked_jsonl_path: str) -> int:
    """One-time import: if stats_snapshot is empty, import legacy JSONL
    snapshots from the baked file and (if present) the live JSONL next to
    users_db_path. Dedups on snapshot_key. Idempotent — a non-empty table
    short-circuits. Returns the number of rows imported."""
    if StatsSnapshot.query.first() is not None:
        return 0

    sources: list[Path] = []
    if baked_jsonl_path:
        sources.append(Path(baked_jsonl_path))
    if users_db_path:
        live = Path(users_db_path).parent / "stats_history.jsonl"
        if live not in sources:
            sources.append(live)

    seen_keys: set[str] = set()
    imported = 0
    for src in sources:
        if not src.exists():
            continue
        try:
            with src.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("skipping corrupt JSONL line in %s", src)
                        continue
                    key = _key_for_jsonl_row(row)
                    if not key or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    payload = {field: row.get(field, {} if field not in
                                              ('grand_total_sites',
                                               'grand_total_entries') else 0)
                               for field in _STAT_FIELDS}
                    recorded_at = row.get('recorded_at') or (
                        datetime.utcfromtimestamp(
                            float(row['db_mtime'])).isoformat() + 'Z'
                        if isinstance(row.get('db_mtime'), (int, float))
                        else None
                    )
                    db.session.add(StatsSnapshot(
                        snapshot_key=key,
                        recorded_at=recorded_at,
                        payload=json.dumps(payload),
                    ))
                    imported += 1
        except OSError:
            logger.exception("failed to read JSONL %s for backfill", src)

    if imported:
        try:
            db.session.commit()
            logger.info("Backfilled %d stats snapshots from JSONL", imported)
        except Exception:
            db.session.rollback()
            logger.exception("stats snapshot backfill commit failed")
            return 0
    return imported
