"""Embeddable coverage-card widget: card-in-frame, JS loader, builder page."""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import quote

from flask import make_response, render_template, request

from config import settings
from coverage_card import render_coverage_card, render_message
from coverage_verdict import signal_verdict
from queries import (
    _fts_addresses,
    find_nearest_stations,
    get_data_date,
    normalize_pl,
    search_addresses,
)

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.abspath(os.path.dirname(__file__))
_STATIONS_DB_PATH = settings.stations_db_path or os.path.join(_BASE_DIR, 'instance', 'stations.db')
_BAKED_ADDRESSES_DB = os.path.join(_BASE_DIR, 'instance', 'addresses.db')

_LOADER_DIST = os.path.join(_BASE_DIR, 'static', 'dist', 'pages', 'embed-coverage-loader.min.js')
_LOADER_SRC = os.path.join(_BASE_DIR, 'static', 'scripts', 'pages', 'embed-coverage-loader.js')

_STRUCTURED_ADDRESS_FIELDS = ('street', 'house_number', 'postal_code', 'city', 'voivodeship')
_COVERAGE_DISCLAIMER = {
    'pl': 'Szacowane na podstawie lokalizacji nadajników UKE i modelu odległościowego — nie pomiar rzeczywistego sygnału; nie uwzględnia terenu, budynków ani obciążenia sieci.',
    'en': 'Estimated from UKE transmitter locations and a distance model — not a real-signal measurement; does not account for terrain, buildings or network load.',
}
_COVERAGE_QUERY_MAX_LEN = 120
_COVERAGE_RADIUS_KM = 5.0
_COVERAGE_CACHE_MAX_AGE = 86400
_COVERAGE_CACHE_SWR = 604800
_LOADER_CACHE_MAX_AGE = 31536000

PL_LAT_MIN, PL_LAT_MAX = 48.95, 55.55
PL_LNG_MIN, PL_LNG_MAX = 13.95, 24.25

_loader_cache: dict = {}


def _addresses_db_path():
    cfg = settings.addresses_db_path
    if cfg and os.path.exists(cfg):
        return cfg
    return _BAKED_ADDRESSES_DB


def _coords_in_bounds(lat, lng):
    return PL_LAT_MIN <= lat <= PL_LAT_MAX and PL_LNG_MIN <= lng <= PL_LNG_MAX


def _assemble_address_query(fields):
    parts = [(fields.get(f) or '').strip() for f in _STRUCTURED_ADDRESS_FIELDS]
    return ' '.join(p for p in parts if p)


def _coverage_block(verdict):
    return {
        'signal_tier': verdict['signal_tier'],
        'signal_score': verdict['signal_score'],
        'real_5g': verdict['real_5g'],
        'operators': verdict['operators'],
    }


def _labels_from_verdict(verdict):
    return {
        'tier_pl': verdict['labels']['pl']['signal_tier'],
        'headline_pl': verdict['labels']['pl']['headline'],
        'real_5g_pl': verdict['labels']['pl']['real_5g'],
        'tier_en': verdict['labels']['en']['signal_tier'],
        'headline_en': verdict['labels']['en']['headline'],
        'real_5g_en': verdict['labels']['en']['real_5g'],
    }


def _resolve_address_coverage(query):
    addresses_db = _addresses_db_path()
    results = search_addresses(query, addresses_db)
    if not results:
        return {'status': 'no_match'}
    best = results[0]
    lat, lng = best['lat'], best['lng']
    tokens = re.findall(r'[a-z0-9]+', normalize_pl(query))
    first_street_token = next((i for i, t in enumerate(tokens) if t.isalpha()), len(tokens))
    has_house_number = any(t.isdigit() for t in tokens[first_street_token + 1:])
    building = bool(has_house_number and _fts_addresses(addresses_db, tokens, 1))
    match = {
        'display': best['display'],
        'latitude': lat,
        'longitude': lng,
        'confidence': 'exact' if building else ('low' if has_house_number else 'medium'),
        'geocode_precision': 'building' if building else 'street_centroid',
    }
    if not _coords_in_bounds(lat, lng):
        return {'status': 'outside_pl', 'match': match}
    verdict = signal_verdict(
        find_nearest_stations(lat, lng, max_distance=_COVERAGE_RADIUS_KM)['stations']
    )
    return {
        'status': 'ok',
        'match': match,
        'is_estimate': not building,
        'coverage': _coverage_block(verdict),
        'labels': _labels_from_verdict(verdict),
    }


def _resolve_coords_coverage(lat, lng):
    match = {
        'display': f'{lat:.5f}, {lng:.5f}',
        'latitude': lat,
        'longitude': lng,
        'confidence': 'exact',
        'geocode_precision': 'coordinate',
    }
    if not _coords_in_bounds(lat, lng):
        return {'status': 'outside_pl', 'match': match}
    verdict = signal_verdict(
        find_nearest_stations(lat, lng, max_distance=_COVERAGE_RADIUS_KM)['stations']
    )
    return {
        'status': 'ok',
        'match': match,
        'is_estimate': True,
        'coverage': _coverage_block(verdict),
        'labels': _labels_from_verdict(verdict),
    }


def _safe_resolve(fn, *args):
    try:
        return fn(*args)
    except Exception:
        logger.exception("embed coverage resolution failed")
        return None


def _build_payload(outcome, query):
    return {
        'status': outcome['status'],
        'query': query,
        'match': outcome.get('match'),
        'coverage': outcome.get('coverage'),
        'labels': outcome.get('labels'),
        'is_estimate': outcome.get('is_estimate'),
        'disclaimer': _COVERAGE_DISCLAIMER,
        'data_date': get_data_date(_STATIONS_DB_PATH),
    }


def _frame(card_html):
    snippet = render_template('embed_coverage.html')
    return card_html.replace('</body>', snippet + '</body>', 1)


def _html_response(html):
    resp = make_response(html)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp


def _message_frame(title, message):
    return _html_response(_frame(render_message(title, message)))


def _load_loader_js():
    if 'js' not in _loader_cache:
        path = _LOADER_DIST if os.path.exists(_LOADER_DIST) else _LOADER_SRC
        with open(path, 'r', encoding='utf-8') as fh:
            _loader_cache['js'] = fh.read()
    return _loader_cache['js']


def register_embed_coverage_routes(app, limiter):

    @limiter.limit("30 per minute")
    def embed_coverage():
        raw_lat = request.args.get('lat')
        raw_lng = request.args.get('lng')
        if raw_lat is not None and raw_lng is not None:
            try:
                lat = float(raw_lat)
                lng = float(raw_lng)
            except (TypeError, ValueError):
                return _message_frame('Nieprawidłowy adres', 'Podaj poprawne współrzędne.'), 400
            query = f'{lat}, {lng}'
            outcome = _safe_resolve(_resolve_coords_coverage, lat, lng)
        else:
            q = (request.args.get('q', type=str, default='') or '').strip()
            structured = {f: (request.args.get(f, type=str, default='') or '').strip()
                          for f in _STRUCTURED_ADDRESS_FIELDS}
            if q and any(structured.values()):
                return _message_frame('Nieprawidłowy adres', 'Podaj q albo pola adresu, nie oba.'), 400
            query = q or _assemble_address_query(structured)
            if len(query) > _COVERAGE_QUERY_MAX_LEN or sum(ch.isalpha() for ch in query) < 3:
                return _message_frame('Nieprawidłowy adres', 'Podaj adres (min. 3 litery).'), 400
            outcome = _safe_resolve(_resolve_address_coverage, query)
        if outcome is None:
            return _message_frame('Błąd', 'Spróbuj ponownie później.'), 500
        payload = _build_payload(outcome, query)
        resp = _html_response(_frame(render_coverage_card(payload)))
        resp.headers['Cache-Control'] = (
            f'public, max-age={_COVERAGE_CACHE_MAX_AGE}, '
            f'stale-while-revalidate={_COVERAGE_CACHE_SWR}'
        )
        return resp

    def embed_coverage_loader():
        resp = make_response(_load_loader_js())
        resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
        resp.headers['Cache-Control'] = f'public, max-age={_LOADER_CACHE_MAX_AGE}, immutable'
        return resp

    def embed_coverage_builder():
        address = (request.args.get('address', type=str, default='') or '').strip()
        lat = (request.args.get('lat', type=str, default='') or '').strip()
        lng = (request.args.get('lng', type=str, default='') or '').strip()
        origin = settings.canonical_origin.rstrip('/')
        if address:
            query = 'q=' + quote(address)
            data_attr = f' data-address="{address}"'
        elif lat and lng:
            query = 'lat=' + quote(lat) + '&lng=' + quote(lng)
            data_attr = f' data-lat="{lat}" data-lng="{lng}"'
        else:
            query = ''
            data_attr = ''
        embed_url = origin + '/embed/coverage' + (f'?{query}' if query else '')
        script_snippet = f'<script src="{origin}/embed/coverage.js"{data_attr} async></script>'
        iframe_snippet = (
            f'<iframe src="{embed_url}" width="100%" '
            f'style="max-width:520px;border:0;height:340px" loading="lazy" '
            f'title="Signal-Scout coverage"></iframe>'
        )
        return render_template(
            'embed_builder.html',
            address=address,
            lat=lat,
            lng=lng,
            embed_origin=origin,
            has_input=bool(query),
            embed_url=embed_url,
            script_snippet=script_snippet,
            iframe_snippet=iframe_snippet,
        )

    app.add_url_rule('/embed/coverage', endpoint='embed_coverage',
                     view_func=embed_coverage, methods=['GET'])
    app.add_url_rule('/embed/coverage.js', endpoint='embed_coverage_loader',
                     view_func=embed_coverage_loader, methods=['GET'])
    app.add_url_rule('/embed/coverage/builder', endpoint='embed_coverage_builder',
                     view_func=embed_coverage_builder, methods=['GET'])
