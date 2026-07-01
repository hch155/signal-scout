"""Real-5G (n78 / C-band 3.5 GHz) rollout snapshot history.

Mirrors stats_history.py: every monthly UKE refresh the /rollout handler
records a snapshot of the 3.5 GHz aggregate (distinct physical sites
broadcasting a >=3400 MHz 5G band, per operator and per voivodeship). The
page reads the previous snapshot and renders month-over-month deltas next
to the current numbers, plus a trend chart over all snapshots.

`real_5g_rollout(stations_db_path)` is the aggregation. It reads stations.db
directly (read-only sqlite, like queries.get_data_date) so it works both in
the live request and in the git-replay backfill — each historical
stations.db blob is just another path.

History lives in the users.db `real_five_g_snapshot` table (created by
Alembic migration 0004) so it shares the persistent mount as the rest of
the user data. `snapshot_key` is the UKE data date (YYYY-MM-DD) — it sorts
chronologically as a string and is UNIQUE, so re-recording the same refresh
is a no-op.

BaseStation carries no voivodeship column, so the region is derived from the
site coordinate by nearest-centroid — self-contained, deterministic, and an
approximation good enough for a rollout tracker.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Optional

from database import db

logger = logging.getLogger(__name__)

HONEYPOT_MARKER = '__HONEYPOT__'
N78_MIN_MHZ = 3400

_REAL5G_FIELDS = (
    'by_operator',
    'by_voivodeship',
    'total_sites',
)

_OPERATOR_PREFIXES = (
    ('orange polska', 'Orange'),
    ('p4 ', 'Play'),
    ('polkomtel', 'Plus'),
    ('t-mobile polska', 'T-Mobile'),
)

_VOIVODESHIP_CENTROIDS = {
    'dolnośląskie': (51.05, 16.30),
    'kujawsko-pomorskie': (53.10, 18.50),
    'lubelskie': (51.15, 22.85),
    'lubuskie': (52.20, 15.30),
    'łódzkie': (51.60, 19.25),
    'małopolskie': (49.85, 20.20),
    'mazowieckie': (52.30, 21.00),
    'opolskie': (50.60, 17.85),
    'podkarpackie': (49.95, 22.20),
    'podlaskie': (53.30, 22.90),
    'pomorskie': (54.15, 18.00),
    'śląskie': (50.30, 18.95),
    'świętokrzyskie': (50.75, 20.70),
    'warmińsko-mazurskie': (53.80, 20.90),
    'wielkopolskie': (52.30, 17.30),
    'zachodniopomorskie': (53.70, 15.60),
}


def operator_label(name: Optional[str]) -> str:
    """Short marketing name for a UKE operator string; the raw name when
    it isn't one of the four majors."""
    if not name:
        return name or ''
    low = name.lower()
    for prefix, label in _OPERATOR_PREFIXES:
        if low.startswith(prefix):
            return label
    return name


def _band_mhz(band: str) -> int:
    m = re.search(r'(\d+)$', band or '')
    return int(m.group(1)) if m else 0


def _is_n78(band: Optional[str]) -> bool:
    return bool(band) and band.startswith('5G') and _band_mhz(band) >= N78_MIN_MHZ


def voivodeship_for(lat: Optional[float], lng: Optional[float]) -> str:
    """Nearest-centroid voivodeship for a coordinate. 'unknown' when the
    coordinate is missing."""
    if lat is None or lng is None:
        return 'unknown'
    best = 'unknown'
    best_d = None
    for name, (clat, clng) in _VOIVODESHIP_CENTROIDS.items():
        d = (lat - clat) ** 2 + (lng - clng) ** 2
        if best_d is None or d < best_d:
            best_d = d
            best = name
    return best


def real_5g_rollout(stations_db_path: str) -> dict:
    """Count distinct 3.5 GHz (n78, >=3400 MHz: 5G3500/5G3600) physical
    sites per operator and per voivodeship from BaseStation.

    A "site" is a distinct (service_provider, location) that broadcasts at
    least one n78 band, mirroring get_band_stats' count(distinct location)
    per operator. `total_sites` == sum(by_operator) == sum(by_voivodeship).
    """
    empty = {'by_operator': {}, 'by_voivodeship': {}, 'total_sites': 0}
    try:
        conn = sqlite3.connect(f"file:{stations_db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return empty
    try:
        rows = conn.execute(
            "SELECT service_provider, AVG(latitude), AVG(longitude), "
            "GROUP_CONCAT(DISTINCT frequency_band) "
            "FROM base_station "
            "WHERE frequency_band LIKE '5G3%' AND service_provider != ? "
            "GROUP BY service_provider, location",
            (HONEYPOT_MARKER,),
        ).fetchall()
    except sqlite3.OperationalError:
        return empty
    finally:
        conn.close()

    by_operator: dict = {}
    by_voivodeship: dict = {}
    total = 0
    for provider, lat, lng, bands_csv in rows:
        if not any(_is_n78(b) for b in (bands_csv or '').split(',')):
            continue
        by_operator[provider] = by_operator.get(provider, 0) + 1
        voiv = voivodeship_for(lat, lng)
        by_voivodeship[voiv] = by_voivodeship.get(voiv, 0) + 1
        total += 1

    return {
        'by_operator': by_operator,
        'by_voivodeship': by_voivodeship,
        'total_sites': total,
    }


def _row_to_dict(row: 'RealFiveGSnapshot') -> dict:
    """Flatten a RealFiveGSnapshot row into the dict callers expect: the
    deserialized payload fields plus snapshot_key + recorded_at."""
    try:
        payload = json.loads(row.payload) if row.payload else {}
    except json.JSONDecodeError:
        logger.warning("corrupt payload for snapshot_key=%s", row.snapshot_key)
        payload = {}
    payload['snapshot_key'] = row.snapshot_key
    payload['recorded_at'] = row.recorded_at
    return payload


def read_real5g_history(users_db_path: Optional[str] = None,
                        limit: Optional[int] = None) -> list[dict]:
    """All snapshots, oldest first (snapshot_key ascending sorts
    chronologically). Optionally cap to the last N."""
    rows = (RealFiveGSnapshot.query
            .order_by(RealFiveGSnapshot.snapshot_key.asc())
            .all())
    out = [_row_to_dict(r) for r in rows]
    if limit is not None:
        out = out[-limit:]
    return out


def previous_real5g_snapshot(users_db_path: Optional[str],
                             current_key: str) -> Optional[dict]:
    """Latest snapshot strictly older than current_key (used by /rollout for
    MoM deltas). None when there's no prior snapshot."""
    if not current_key:
        return None
    row = (RealFiveGSnapshot.query
           .filter(RealFiveGSnapshot.snapshot_key < current_key)
           .order_by(RealFiveGSnapshot.snapshot_key.desc())
           .first())
    return _row_to_dict(row) if row else None


def maybe_write_real5g_snapshot(users_db_path: Optional[str], data_date: str,
                                rollout: dict,
                                recorded_at_override: Optional[str] = None) -> bool:
    """Insert a snapshot keyed on data_date if none exists for that key yet.
    Returns True iff a new row was inserted.

    `recorded_at_override` lets backfill stamp the snapshot with the date the
    data refers to; live runs pass None and get utcnow()."""
    if not data_date:
        return False
    exists = (RealFiveGSnapshot.query
              .filter_by(snapshot_key=data_date)
              .first())
    if exists is not None:
        return False
    payload = {field: rollout.get(field, 0 if field == 'total_sites' else {})
               for field in _REAL5G_FIELDS}
    recorded_at = recorded_at_override or (datetime.utcnow().isoformat() + 'Z')
    db.session.add(RealFiveGSnapshot(
        snapshot_key=data_date,
        recorded_at=recorded_at,
        payload=json.dumps(payload),
    ))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.info("real5g snapshot for %s already written by a concurrent worker",
                    data_date)
        return False
    logger.info("Recorded real5g rollout snapshot for %s", data_date)
    return True


def backfill_real5g_from_jsonl(users_db_path: Optional[str],
                               baked_jsonl_path: str) -> int:
    """Load baked JSONL rollout snapshots (git-history replay output) for any
    snapshot_key not already stored, so /rollout shows the full trend on a fresh
    deploy where the git history isn't available. Idempotent — already-present
    keys are skipped (prod already holds the 1-2 live snapshots). Returns rows
    imported."""
    existing = {
        k for (k,) in RealFiveGSnapshot.query.with_entities(
            RealFiveGSnapshot.snapshot_key).all()
    }
    sources = []
    if baked_jsonl_path:
        sources.append(baked_jsonl_path)
    if users_db_path:
        live = os.path.join(os.path.dirname(users_db_path),
                            'real5g_rollout_history.jsonl')
        if live not in sources:
            sources.append(live)
    seen: set = set()
    imported = 0
    for src in sources:
        if not os.path.exists(src):
            continue
        try:
            with open(src, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("skipping corrupt real5g JSONL line in %s", src)
                        continue
                    key = row.get('snapshot_key')
                    if not key or key in seen or key in existing:
                        continue
                    seen.add(key)
                    payload = {field: row.get(field, 0 if field == 'total_sites' else {})
                               for field in _REAL5G_FIELDS}
                    db.session.add(RealFiveGSnapshot(
                        snapshot_key=key,
                        recorded_at=row.get('recorded_at'),
                        payload=json.dumps(payload),
                    ))
                    imported += 1
        except OSError:
            logger.exception("failed to read real5g JSONL %s", src)
    if imported:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("real5g jsonl backfill commit failed")
            return 0
    logger.info("Backfilled %d real5g rollout snapshots from JSONL", imported)
    return imported


class RealFiveGSnapshot(db.Model):
    """Monthly 3.5 GHz rollout snapshot. One row per UKE refresh.

    `snapshot_key` is the data date (YYYY-MM-DD), UNIQUE so re-recording the
    same refresh is idempotent and ascending string sort == chronological
    order. `payload` is the JSON-encoded aggregate (by_operator,
    by_voivodeship, total_sites). `recorded_at` is the ISO time we observed
    it. Defined here (not models.py) to keep the feature self-contained;
    table is created by Alembic migration 0004.
    """
    __bind_key__ = 'users'
    __tablename__ = 'real_five_g_snapshot'

    id = db.Column(db.Integer, primary_key=True)
    snapshot_key = db.Column(db.Text, unique=True, nullable=False)
    recorded_at = db.Column(db.Text)
    payload = db.Column(db.Text, nullable=False)
