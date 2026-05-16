"""Append-only stats snapshot history.

Each time the underlying stations.db file changes (monthly UKE
refresh), the get_stats() handler appends a snapshot of the
aggregates here. The /stats page then reads the previous snapshot
and renders month-over-month deltas next to the current numbers.

Storage shape: JSONL (one snapshot per line) at
`<users_db_dir>/stats_history.jsonl`. On Cloud Run that's the
gcsfuse mount `/mnt/users-db/`, so history survives deploys + scale-
to-zero. Local dev writes to `src/instance/`.

Why JSONL and not SQLite:
- Append is one line, no migration story.
- Whole file read is fine — at one snapshot per month, file grows
  ~12 lines/year × ~1 KB ≈ 12 KB/year. We will not have a million
  snapshots.
- Easy to inspect / export — `cat stats_history.jsonl | jq` works.

Why per-(db_mtime) dedupe:
- Boot fires once per cold-start; without dedupe, every Cloud Run
  cold start would write a new (identical) snapshot.
- We key on `db_mtime` rounded to the second so jitter from
  filesystem-mtime resolution doesn't double-count.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _snapshot_path(users_db_path: str) -> Path:
    """Compute the JSONL path next to users.db (so it lives on the
    same persistent mount in production)."""
    return Path(users_db_path).parent / "stats_history.jsonl"


def _read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("skipping corrupt snapshot line in %s", path)
        return out
    except OSError:
        logger.exception("read of %s failed", path)
        return []


def read_history(users_db_path: str, limit: Optional[int] = None) -> list[dict]:
    """Return all snapshots, oldest first. Optionally cap to last N."""
    rows = _read_all(_snapshot_path(users_db_path))
    if limit is not None:
        rows = rows[-limit:]
    return rows


def previous_snapshot(users_db_path: str, current_db_mtime: float) -> Optional[dict]:
    """Latest snapshot strictly older than the current db_mtime.

    Used by /stats to compute MoM deltas: 'sites: 20,557 (+247 since
    last refresh)'. Returns None when there's no prior snapshot
    (first run, or only the current one is recorded)."""
    rows = _read_all(_snapshot_path(users_db_path))
    older = [r for r in rows
             if isinstance(r.get('db_mtime'), (int, float))
             and r['db_mtime'] + 1.0 < current_db_mtime]
    return older[-1] if older else None


def maybe_write_snapshot(users_db_path: str, db_mtime: float,
                          stats: dict,
                          recorded_at_override: Optional[str] = None) -> bool:
    """Append a snapshot if no snapshot exists for this db_mtime yet.
    Returns True iff a new line was appended.

    `recorded_at_override` lets the historical-replay scripts stamp the
    snapshot with the date the data refers to (e.g. 2025-04-25T20:00:00Z)
    rather than wall-clock time. Live runs (Cloud Run /stats hit) pass
    None and get utcnow() — which is the right answer for those, since
    they're recording 'we observed this NOW'."""
    if not db_mtime:
        return False
    path = _snapshot_path(users_db_path)
    rows = _read_all(path)
    for r in rows:
        if abs((r.get('db_mtime') or 0) - db_mtime) < 1.0:
            return False  # already snapshotted this refresh

    snapshot = {
        'db_mtime': float(db_mtime),
        'recorded_at': recorded_at_override or (
            datetime.utcnow().isoformat() + 'Z'
        ),
        'physical_sites': stats.get('physical_sites', {}),
        'sites_per_generation': stats.get('sites_per_generation', {}),
        'provider_totals': stats.get('provider_totals', {}),
        'generation_breakdown': stats.get('generation_breakdown', {}),
        'generation_totals': stats.get('generation_totals', {}),
        'grand_total_sites': stats.get('grand_total_sites', 0),
        'grand_total_entries': stats.get('grand_total_entries', 0),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(snapshot) + '\n')
        logger.info("Recorded stats snapshot at %s (db_mtime=%s)",
                    path, db_mtime)
        return True
    except OSError:
        logger.exception("failed to append stats snapshot to %s", path)
        return False
