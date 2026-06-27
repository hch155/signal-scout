"""Coverage-alert subscription by address.

A logged-in user who is looking at a coverage / best-operator result can
hit "Subscribe to coverage changes at this address". We geocode the
address with the same pipeline the public coverage card uses
(app._resolve_address_coverage) and upsert an alerting-enabled
UserLocation — the existing coverage-alert sweep
(coverage_alerts.run_coverage_alert_sweep) then emails them after the
monthly UKE refresh whenever coverage there materially changes.

Scope is deliberately logged-in only. The sweep already skips users whose
email is unverified, so reusing UserLocation lets us ship without a
separate unverified-subscription table.

real5g_delta() is the sweep-side classifier: it flags when a >= 3400 MHz
("real 5G") band is gained or lost between two coverage snapshots, so the
alert email can lead with "Real 5G now available".
"""
from __future__ import annotations

import logging
from typing import Optional

from database import db
from models import UserLocation
from coverage_verdict import parse_5g_mhz, REAL_5G_MIN_MHZ
from auth_routes import (
    _MAX_LOCATIONS_PER_USER,
    _LOC_NAME_MAX,
    _LOC_RADIUS_DEFAULT_KM,
)

logger = logging.getLogger(__name__)


def subscribe_address(user, query: str) -> dict:
    """Geocode `query` and upsert an alerting-enabled UserLocation for
    `user`. Returns a status dict mirroring _resolve_address_coverage:

      {'status': 'ok', 'created': bool, 'location': UserLocation, 'match': {...}}
      {'status': 'no_match'}
      {'status': 'outside_pl', 'match': {...}}
      {'status': 'limit_reached', 'limit': int}

    Upsert key is (user_id, geocoded display name): re-subscribing to the
    same address re-arms alerting and refreshes the coordinates instead of
    stacking duplicates. Geocoding reuses app._resolve_address_coverage
    (lazy import to dodge the app <-> blueprint import cycle).
    """
    from app import _resolve_address_coverage

    outcome = _resolve_address_coverage(query)
    status = outcome.get('status')
    if status == 'no_match':
        return {'status': 'no_match'}
    if status == 'outside_pl':
        return {'status': 'outside_pl', 'match': outcome.get('match')}

    match = outcome['match']
    name = (match.get('display') or query).strip()[:_LOC_NAME_MAX]
    lat = float(match['latitude'])
    lng = float(match['longitude'])

    existing = (UserLocation.query
                .filter_by(user_id=user.id, name=name)
                .first())
    if existing is not None:
        existing.lat = lat
        existing.lng = lng
        existing.alerting_enabled = True
        db.session.commit()
        return {'status': 'ok', 'created': False,
                'location': existing, 'match': match}

    if UserLocation.query.filter_by(user_id=user.id).count() >= _MAX_LOCATIONS_PER_USER:
        return {'status': 'limit_reached', 'limit': _MAX_LOCATIONS_PER_USER}

    loc = UserLocation(
        user_id=user.id,
        name=name,
        lat=lat,
        lng=lng,
        radius_km=_LOC_RADIUS_DEFAULT_KM,
        alerting_enabled=True,
    )
    db.session.add(loc)
    db.session.commit()
    return {'status': 'ok', 'created': True, 'location': loc, 'match': match}


def _covered_real5g_bands(snapshot: Optional[dict]) -> set:
    """Set of covered band codes in `snapshot` whose 5G frequency is at or
    above REAL_5G_MIN_MHZ. `snapshot` is a coverage_alerts._coverage_to_dict
    snapshot ({'gaps': [{band, has_coverage, ...}]})."""
    bands = set()
    for g in (snapshot or {}).get('gaps', []):
        if not g.get('has_coverage'):
            continue
        mhz = parse_5g_mhz(g.get('band'))
        if mhz is not None and mhz >= REAL_5G_MIN_MHZ:
            bands.add(g.get('band'))
    return bands


def real5g_delta(before: Optional[dict], after: Optional[dict]) -> dict:
    """Classify the real-5G change between two coverage snapshots.

    Returns {'gained': bool, 'lost': bool, 'gained_bands': [...],
    'lost_bands': [...]}: `gained` means a >= 3400 MHz band became covered
    (so the alert can lead with "Real 5G now available"); `lost` means one
    dropped out of coverage. Band lists are sorted band codes."""
    before_bands = _covered_real5g_bands(before)
    after_bands = _covered_real5g_bands(after)
    gained_bands = sorted(after_bands - before_bands)
    lost_bands = sorted(before_bands - after_bands)
    return {
        'gained': bool(gained_bands),
        'lost': bool(lost_bands),
        'gained_bands': gained_bands,
        'lost_bands': lost_bands,
    }
