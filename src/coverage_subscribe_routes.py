"""POST /coverage/subscribe — login-required coverage-alert subscription
by address.

Registered from app.py via register_coverage_subscribe_routes(app, limiter)
rather than folded into the auth blueprint so the whole subscribe feature
ships as one self-contained unit (module + blueprint + template + JS).
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, session

from database import db
from models import User
from coverage_subscribe import subscribe_address, subscribe_coords

logger = logging.getLogger(__name__)

coverage_subscribe_bp = Blueprint("coverage_subscribe", __name__)

_QUERY_MAX_LEN = 120
_QUERY_MIN_ALPHA = 3


def _serialize(loc) -> dict:
    return {
        'id': loc.id,
        'name': loc.name,
        'lat': loc.lat,
        'lng': loc.lng,
        'alerting_enabled': bool(loc.alerting_enabled),
    }


def coverage_subscribe():
    from app import validate_csrf
    from observability import csrf_failures_total

    if not validate_csrf():
        csrf_failures_total.labels(endpoint='coverage_subscribe').inc()
        return jsonify({'error': 'Invalid request'}), 403

    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    user = db.session.get(User, session['user_id'])
    if user is None:
        session.pop('user_id', None)
        return jsonify({'error': 'Authentication required'}), 401

    payload = request.get_json(silent=True) or request.form
    lat_raw, lng_raw = payload.get('lat'), payload.get('lng')
    use_coords = lat_raw not in (None, '') and lng_raw not in (None, '')

    # A GPS fix or a manual map pin subscribes by coordinates (labelled with
    # the nearest-city name the frontend already shows); an address search
    # still subscribes by its geocoded query.
    if use_coords:
        try:
            lat, lng = float(lat_raw), float(lng_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid_input'}), 400
        name = (payload.get('name') or '').strip()
    else:
        query = (payload.get('query') or '').strip()
        if len(query) > _QUERY_MAX_LEN or sum(ch.isalpha() for ch in query) < _QUERY_MIN_ALPHA:
            return jsonify({'error': 'invalid_input'}), 400

    try:
        result = (subscribe_coords(user, lat, lng, name) if use_coords
                  else subscribe_address(user, query))
    except Exception:
        logger.exception("coverage_subscribe failed for user_id=%s", user.id)
        db.session.rollback()
        return jsonify({'error': 'internal_error'}), 500

    status = result['status']
    if status == 'no_match':
        return jsonify({'error': 'no_match'}), 404
    if status == 'outside_pl':
        return jsonify({'error': 'outside_pl', 'match': result.get('match')}), 400
    if status == 'limit_reached':
        return jsonify({'error': 'limit_reached', 'limit': result['limit']}), 400

    return jsonify({
        'success': True,
        'created': result['created'],
        'location': _serialize(result['location']),
        'match': result.get('match'),
    }), 200


def register_coverage_subscribe_routes(app, limiter):
    """Wire POST /coverage/subscribe onto `app`. Called from app.py next to
    register_auth_routes (db + limiter must already exist)."""
    coverage_subscribe_bp.add_url_rule(
        "/coverage/subscribe",
        endpoint="coverage_subscribe",
        view_func=limiter.limit("20 per hour")(coverage_subscribe),
        methods=["POST"],
    )
    app.register_blueprint(coverage_subscribe_bp)
