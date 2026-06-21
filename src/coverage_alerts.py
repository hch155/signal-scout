"""Coverage-alert sweep — shared by the CLI runner + the admin
endpoint.

For every UserLocation with alerting_enabled=True:
  1. Compute current coverage gaps (find_coverage_gaps).
  2. Diff against last_coverage_state (JSON snapshot persisted on the
     row from the previous run).
  3. If anything materially changed (band gained / lost / nearest-BTS
     distance moved more than MIN_DISTANCE_DELTA_KM), send the
     coverage-alert email + stamp the new snapshot.

Originally this lived as a one-shot inside scripts/coverage_alert_
run.py. The 2026-04-28 split moves the actual work here so /admin/
run_coverage_alerts (Cloud-Scheduler-callable) can re-use it without
shelling out to a script. The script keeps an argparse CLI that
just calls run_coverage_alert_sweep().
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from database import db
from models import UserLocation, User
from queries import find_coverage_gaps
import emails


MIN_DISTANCE_DELTA_KM = 1.0  # ignore wobble below this — tile changes etc

logger = logging.getLogger('coverage_alerts')


def _coverage_to_dict(cov: dict) -> dict:
    """Reduce find_coverage_gaps output to the bits we actually diff,
    plus the nearest-BTS labels (basestation_id / city / provider) so
    the email can name the actual tower instead of just the band code.
    Snapshot stays compact; no full row dump."""
    return {
        'gaps': [
            {
                'band': g['band'],
                'nearest_distance_km': float(g.get('nearest_distance_km', 0.0)),
                'has_coverage': bool(g.get('has_coverage', False)),
                'nearest_basestation_id': g.get('nearest_basestation_id'),
                'nearest_city': g.get('nearest_city'),
                'nearest_service_provider': g.get('nearest_service_provider'),
            }
            for g in cov.get('gaps', [])
        ],
        'recorded_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
    }


_PROVIDER_SHORT = {
    'P4 Sp. z o.o.': 'Play',
    'P4 sp. z o.o.': 'Play',
    'Orange Polska S.A.': 'Orange',
    'T-Mobile Polska S.A.': 'T-Mobile',
    'POLKOMTEL Sp. z o.o.': 'Plus',
    'Polkomtel sp. z o.o.': 'Plus',
}


def _row_label(g: dict) -> dict:
    """Pull the BTS-identification fields out of a snapshot gap row,
    normalised. Templates render {bts_id, city, provider}."""
    provider = g.get('nearest_service_provider') or ''
    return {
        'bts_id': g.get('nearest_basestation_id'),
        'city': g.get('nearest_city'),
        'provider': _PROVIDER_SHORT.get(provider, provider),
    }


def _diff(before: dict, after: dict):
    """Return (gained, lost, distance_changes).

    gained / lost are lists of dicts: {band, bts_id, city, provider}
      — gained uses the AFTER snapshot's BTS labels (the new tower we
        just came in range of); lost uses the BEFORE snapshot's labels
        (the tower we drifted away from).
    distance_changes is a list of dicts:
      {band, before_km, after_km, delta_km, before_bts, after_bts}
      where before_bts / after_bts are {bts_id, city, provider} dicts.
    Only bands present in BOTH snapshots whose nearest-BTS distance moved
    by more than MIN_DISTANCE_DELTA_KM are included."""
    before_by_band = {g['band']: g for g in before.get('gaps', [])}
    after_by_band = {g['band']: g for g in after.get('gaps', [])}

    before_covered = {b for b, g in before_by_band.items() if g['has_coverage']}
    after_covered = {b for b, g in after_by_band.items() if g['has_coverage']}

    gained = [
        {'band': b, **_row_label(after_by_band[b])}
        for b in sorted(after_covered - before_covered)
    ]
    lost = [
        {'band': b, **_row_label(before_by_band[b])}
        for b in sorted(before_covered - after_covered)
    ]

    distance_changes = []
    for band, after_g in after_by_band.items():
        if band not in before_by_band:
            continue
        before_g = before_by_band[band]
        delta = after_g['nearest_distance_km'] - before_g['nearest_distance_km']
        if abs(delta) >= MIN_DISTANCE_DELTA_KM:
            distance_changes.append({
                'band': band,
                'before_km': before_g['nearest_distance_km'],
                'after_km': after_g['nearest_distance_km'],
                'delta_km': delta,
                'before_bts': _row_label(before_g),
                'after_bts': _row_label(after_g),
            })
    distance_changes.sort(key=lambda c: -abs(c['delta_km']))

    return gained, lost, distance_changes


def _process(loc: UserLocation, *, dry_run: bool, verbose: bool) -> str:
    """Return a one-word status: 'first-run', 'no-change', 'sent',
    'send-failed', 'skipped'."""
    after = _coverage_to_dict(find_coverage_gaps(loc.lat, loc.lng))
    after_json = json.dumps(after, sort_keys=True)

    before = None
    if loc.last_coverage_state:
        try:
            before = json.loads(loc.last_coverage_state)
        except Exception:
            logger.exception(
                "loc id=%s has malformed last_coverage_state — treating as first run",
                loc.id,
            )
            before = None

    if before is None:
        if not dry_run:
            loc.last_coverage_state = after_json
            db.session.commit()
        if verbose:
            logger.info(
                "loc id=%s user=%s name=%r → first-run, snapshot stored",
                loc.id, loc.user_id, loc.name,
            )
        return 'first-run'

    gained, lost, distance_changes = _diff(before, after)

    if not gained and not lost and not distance_changes:
        if not dry_run:
            loc.last_coverage_state = after_json
            db.session.commit()
        if verbose:
            logger.info(
                "loc id=%s user=%s name=%r → no meaningful change",
                loc.id, loc.user_id, loc.name,
            )
        return 'no-change'

    user = User.query.get(loc.user_id)
    if user is None:
        logger.warning(
            "loc id=%s references missing user_id=%s — skipping",
            loc.id, loc.user_id,
        )
        return 'skipped'
    if not user.email_verified:
        logger.info(
            "loc id=%s user_id=%s skipped (email unverified)",
            loc.id, user.id,
        )
        return 'skipped'

    logger.info(
        "loc id=%s user_id=%s name=%r → diff: gained=%s lost=%s distance_changes=%d",
        loc.id, user.id, loc.name,
        gained or '-', lost or '-', len(distance_changes),
    )

    if dry_run:
        return 'sent'  # would have sent

    current_nearest = None
    covered = [g for g in (after.get('gaps') or []) if g.get('has_coverage')]
    if covered:
        c = min(covered, key=lambda g: g.get('nearest_distance_km', 99.0))
        current_nearest = {
            'band': c.get('band'),
            'distance_km': c.get('nearest_distance_km'),
            **_row_label(c),
        }

    ok = emails.send_coverage_alert(
        user, loc, gained, lost, distance_changes,
        before_recorded_at=before.get('recorded_at'),
        current_nearest=current_nearest,
    )
    if ok:
        loc.last_alert_sent_at = datetime.utcnow()
    loc.last_coverage_state = after_json
    db.session.commit()
    return 'sent' if ok else 'send-failed'


def run_coverage_alert_sweep(*, dry_run: bool = False,
                              user_id: Optional[int] = None,
                              verbose: bool = False) -> dict:
    """Process every alerting-enabled UserLocation. Returns a status-
    counts dict — drop-in for both the CLI logger and the admin
    endpoint JSON response.

    MUST be called inside an active Flask app context (the script
    runner pushes one explicitly; the admin endpoint is already
    inside one for the duration of the request)."""
    import os as _os
    import time as _t

    counts = {
        'first-run': 0, 'no-change': 0, 'sent': 0,
        'send-failed': 0, 'skipped': 0, 'error': 0,
    }

    if _os.getenv('COVERAGE_ALERTS_DISABLED', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        logger.info("coverage sweep killed by COVERAGE_ALERTS_DISABLED env var — exit 0, no work done")
        counts['total_processed'] = 0
        return counts

    q = UserLocation.query.filter_by(alerting_enabled=True)
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    locs = q.order_by(UserLocation.id).all()

    started = _t.time()
    for loc in locs:
        try:
            status = _process(loc, dry_run=dry_run, verbose=verbose)
        except Exception:
            logger.exception(
                "coverage sweep: _process raised for loc id=%s user_id=%s — counted as error, continuing",
                loc.id, loc.user_id,
            )
            db.session.rollback()
            status = 'error'
        counts[status] = counts.get(status, 0) + 1
    elapsed = _t.time() - started
    counts['total_processed'] = sum(
        counts[k] for k in
        ('first-run', 'no-change', 'sent', 'send-failed', 'skipped', 'error')
    )

    try:
        from observability import (
            coverage_alert_sweep_seconds,
            coverage_alert_sweep_sent_total,
            coverage_alert_sweep_last_run_timestamp,
        )
        coverage_alert_sweep_seconds.observe(elapsed)
        for status in ('first-run', 'no-change', 'sent', 'send-failed', 'skipped', 'error'):
            n = counts.get(status, 0)
            if n:
                coverage_alert_sweep_sent_total.labels(status=status).inc(n)
        coverage_alert_sweep_last_run_timestamp.set(_t.time())
    except Exception:
        logger.exception("coverage_alert_sweep metrics emit failed")

    return counts
