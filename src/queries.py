import math
import logging
import os
import re
import sqlite3
from datetime import datetime
from models import BaseStation, db
from sqlalchemy import func, distinct, case

logger = logging.getLogger(__name__)

_PL_FOLD = str.maketrans('ąćęłńóśźż', 'acelnoszz')


def normalize_pl(text):
    return (text or '').lower().translate(_PL_FOLD)


def _fts_addresses(db_path, tokens, limit):
    # House numbers match exactly; street/city words match as a prefix.
    match = ' '.join((t if t.isdigit() else t + '*') for t in tokens)
    try:
        con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    except sqlite3.OperationalError:
        return []
    try:
        rows = con.execute(
            "SELECT a.display, a.lat, a.lng FROM addresses_fts f "
            "JOIN addresses a ON a.id = f.rowid "
            "WHERE addresses_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return [{'display': d, 'lat': lat, 'lng': lng} for d, lat, lng in rows]


def search_addresses(query, db_path, limit=8):
    tokens = re.findall(r'[a-z0-9]+', normalize_pl(query))
    if not tokens or sum(len(t) for t in tokens) < 3:
        return []
    rows = _fts_addresses(db_path, tokens, limit)
    if not rows:
        # Street-level data has no house numbers — retry without the number so
        # "Łąkowa 5 Białystok" still finds the street. (v2 matches it directly.)
        alpha = [t for t in tokens if not t.isdigit()]
        if alpha and len(alpha) != len(tokens) and sum(len(t) for t in alpha) >= 3:
            rows = _fts_addresses(db_path, alpha, limit)
    return rows


def get_data_date(stations_db_path):
    """Return the UKE data date (YYYY-MM-DD) for the stations.db.

    Prefers the `data_date` row in the stations.db `metadata` table (written
    by scripts/stations_database_setup.py). Falls back to the file's mtime for
    DBs built before the metadata table existed; returns 'unknown' if even
    that can't be read.
    """
    try:
        conn = sqlite3.connect(f"file:{stations_db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key = 'data_date'"
            ).fetchone()
            if row and row[0]:
                return row[0]
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    try:
        return datetime.utcfromtimestamp(
            os.path.getmtime(stations_db_path)
        ).strftime('%Y-%m-%d')
    except OSError:
        return 'unknown'

def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    r = 6371
    return c * r

def sort_frequency_bands(bands):
    def get_sort_key(band):
        if band.startswith('5G'):
            priority = 1
        elif band.startswith('LTE'):
            priority = 2
        elif band.startswith('UMTS'):
            priority = 3
        elif band.startswith('GSM'):
            priority = 4
        else:
            priority = 5

        numeric_part = int(''.join(filter(str.isdigit, band))) if any(char.isdigit() for char in band) else 0
        return (priority, -numeric_part, band)

    return sorted(bands, key=get_sort_key)

def get_latitude_segment(latitude):
    """Returns the segment index for a given latitude."""
    base_latitude = 49.0
    segment_size = 0.1
    return int((latitude - base_latitude) / segment_size)


COVERAGE_THRESHOLDS_KM = {
    "5G3600": 1.5,
    "LTE2600": 1.5,
    "5G2100": 2.0,
    "LTE2100": 2.0,
    "LTE1800": 2.0,
    "UMTS2100": 2.0,
    "LTE800": 5.0,
    "L900": 5.0,
    "GSM900": 5.0,
    "G900": 5.0,
}
DEFAULT_GAP_THRESHOLD_KM = 3.0
GAP_SEARCH_SEGMENTS = 3


def find_coverage_gaps(user_lat: float, user_lng: float) -> dict:
    """Per-band 'dead area' detection at a single point.

    For each frequency band present in the dataset, returns the
    distance to the nearest BTS of that band and whether that distance
    falls inside the band-specific 'poor-coverage' threshold. A 'gap'
    is a band whose nearest station is farther than the threshold —
    meaning a phone configured for that band would lose signal here.

    Output shape:
      {
        'gaps': [
          {'band': '5G3600', 'nearest_distance_km': 4.2,
           'threshold_km': 1.5, 'has_coverage': False},
          ...
        ],
        'summary': {'total_bands': 8, 'covered': 6, 'dead': 2}
      }

    Used by GET /api/v1/coverage_gaps; surfaced in the sidebar after
    every map click.
    """
    user_segment = get_latitude_segment(user_lat)
    segments = list(range(
        user_segment - GAP_SEARCH_SEGMENTS,
        user_segment + GAP_SEARCH_SEGMENTS + 1,
    ))

    try:
        rows = db.session.query(
            BaseStation.frequency_band,
            BaseStation.latitude,
            BaseStation.longitude,
            BaseStation.service_provider,
            BaseStation.basestation_id,
            BaseStation.city,
            BaseStation.location,
        ).filter(
            BaseStation.latitude_segment.in_(segments)
        ).filter(
            BaseStation.service_provider != '__HONEYPOT__'
        ).all()
    except Exception as e:
        logger.error(f"Error in find_coverage_gaps query: {e}")
        return {"gaps": [], "summary": {"total_bands": 0, "covered": 0, "dead": 0}}

    nearest_per_band: dict[str, dict] = {}
    bands_at_loc: dict[tuple, set] = {}
    for band, lat, lng, provider, bts_id, city, location in rows:
        if not band:
            continue
        d = haversine(user_lat, user_lng, lat, lng)
        prev = nearest_per_band.get(band)
        if prev is None or d < prev["dist"]:
            nearest_per_band[band] = {
                "dist": d,
                "lat": lat,
                "lng": lng,
                "provider": provider,
                "basestation_id": bts_id,
                "city": city,
                "location": location,
            }
        loc_key = (round(lat, 6), round(lng, 6), provider)
        bands_at_loc.setdefault(loc_key, set()).add(band)

    gaps = []
    for band in sort_frequency_bands(list(nearest_per_band.keys())):
        info = nearest_per_band[band]
        dist = info["dist"]
        threshold = COVERAGE_THRESHOLDS_KM.get(band, DEFAULT_GAP_THRESHOLD_KM)
        loc_key = (round(info["lat"], 6), round(info["lng"], 6), info["provider"])
        all_bands = sort_frequency_bands(list(bands_at_loc.get(loc_key, {band})))
        gaps.append({
            "band": band,
            "nearest_distance_km": round(dist, 2),
            "nearest_lat": info["lat"],
            "nearest_lng": info["lng"],
            "nearest_basestation_id": info["basestation_id"],
            "nearest_service_provider": info["provider"],
            "nearest_city": info["city"],
            "nearest_location": info["location"],
            "nearest_frequency_bands": all_bands,
            "threshold_km": threshold,
            "has_coverage": dist <= threshold,
        })

    summary = {
        "total_bands": len(gaps),
        "covered": sum(1 for g in gaps if g["has_coverage"]),
        "dead": sum(1 for g in gaps if not g["has_coverage"]),
    }
    return {"gaps": gaps, "summary": summary}

def find_nearest_stations(user_lat, user_lng, limit=None, max_distance=None, service_providers=[], frequency_bands=[]):
    HONEYPOT_MARKER = '__HONEYPOT__'
    user_segment = get_latitude_segment(user_lat)
    adjacent_segments = [user_segment - 1, user_segment, user_segment + 1]

    try:
        query = db.session.query(
            BaseStation.basestation_id,
            BaseStation.city,
            BaseStation.service_provider,
            BaseStation.location,
            BaseStation.latitude,
            BaseStation.longitude,
            func.group_concat(BaseStation.frequency_band.distinct())
        ).filter(
            BaseStation.latitude_segment.in_(adjacent_segments)
        ).filter(
            BaseStation.service_provider != HONEYPOT_MARKER
        )

        if service_providers:
            query = query.filter(BaseStation.service_provider.in_(service_providers))
        if frequency_bands:
            query = query.filter(BaseStation.frequency_band.in_(frequency_bands))

        query = query.group_by(BaseStation.latitude, BaseStation.longitude, BaseStation.service_provider)
        grouped_rows = query.all()

        stations_with_distance = []
        for row in grouped_rows:
            basestation_id, city, provider, location, lat, lng, bands_csv = row
            distance = haversine(user_lat, user_lng, lat, lng)

            if max_distance is not None and distance > max_distance:
                continue

            bands_list = sort_frequency_bands(bands_csv.split(',')) if bands_csv else []
            stations_with_distance.append({
                'basestation_id': basestation_id,
                'city': city,
                'service_provider': provider,
                'location': location,
                'latitude': lat,
                'longitude': lng,
                'frequency_bands': bands_list,
                'distance': round(distance, 2)
            })

        stations_with_distance.sort(key=lambda x: x['distance'])
        if limit is not None:
            stations_with_distance = stations_with_distance[:limit]

        return {"stations": stations_with_distance, "count": len(stations_with_distance)}

    except Exception as e:
        logger.error(f"Error in find_nearest_stations: {e}")
        return {"stations": [], "count": 0}

def get_band_stats():
    HONEYPOT_MARKER = '__HONEYPOT__'

    # Query for physical site counts per provider
    physical_sites_query = (
        db.session.query(
            BaseStation.service_provider,
            func.count(distinct(BaseStation.location))
        )
        .filter(BaseStation.service_provider != HONEYPOT_MARKER)
        .group_by(BaseStation.service_provider).all()
    )

    # Query for band counts per provider
    band_counts_query = (
        db.session.query(
            BaseStation.service_provider,
            BaseStation.frequency_band,
            func.count(BaseStation.frequency_band)
        )
        .filter(BaseStation.service_provider != HONEYPOT_MARKER)
        .group_by(BaseStation.service_provider,
                  BaseStation.frequency_band).all()
    )

    rat_prefix_case = case(
        (BaseStation.frequency_band.like('5G%'), '5G'),
        (BaseStation.frequency_band.like('LTE%'), 'LTE'),
        (BaseStation.frequency_band.like('UMTS%'), 'UMTS'),
        (BaseStation.frequency_band.like('GSM%'), 'GSM'),
        else_='Other',
    )
    sites_per_gen_query = (
        db.session.query(
            BaseStation.service_provider,
            rat_prefix_case.label('gen'),
            func.count(distinct(BaseStation.location)),
        )
        .filter(BaseStation.service_provider != HONEYPOT_MARKER)
        .group_by(BaseStation.service_provider, 'gen')
        .all()
    )

    # Organize data
    providers = set()
    bands_data = {}
    for provider, band, count in band_counts_query:
        providers.add(provider)
        if band not in bands_data:
            bands_data[band] = {}
        bands_data[band][provider] = count

    sites_per_generation: dict = {}
    for provider, gen, n in sites_per_gen_query:
        sites_per_generation.setdefault(provider, {})[gen] = n

    return {
        'physical_sites': dict(physical_sites_query),
        'bands_data': bands_data,
        'providers': sorted(providers),
        'sites_per_generation': sites_per_generation,
    }

def get_stats():
    stats = get_band_stats()
    band_order = ['5G3600', '5G2100', '5G1800', '5G700', 'LTE2600', 'LTE2100', 'LTE1800', 'LTE900', 'LTE800', 'LTE700', 'UMTS2100', 'UMTS900', 'GSM1800', 'GSM900']

    def band_sort_key(band):
        if band in band_order:
            return band_order.index(band)
        return len(band_order)  # Place unknown bands at the end

    sorted_bands = sorted(stats['bands_data'].keys(), key=band_sort_key)

    providers = stats['providers']
    bands_data = stats['bands_data']

    def _gen_of(band: str) -> str:
        for prefix in ('5G', 'LTE', 'UMTS', 'GSM'):
            if band.startswith(prefix):
                return prefix
        return 'Other'

    # Per-band sum across operators (rightmost "Total" column).
    band_totals = {
        band: sum(bands_data[band].values()) for band in sorted_bands
    }
    # Per-provider total entries (across all bands).
    provider_totals = {
        p: sum(bands_data[band].get(p, 0) for band in sorted_bands)
        for p in providers
    }
    generations = ['5G', 'LTE', 'UMTS', 'GSM']
    generation_breakdown: dict = {p: {g: 0 for g in generations} for p in providers}
    for band in sorted_bands:
        gen = _gen_of(band)
        if gen not in generations:
            continue
        for p in providers:
            generation_breakdown[p][gen] += bands_data[band].get(p, 0)
    generation_totals = {
        g: sum(generation_breakdown[p][g] for p in providers)
        for g in generations
    }

    HONEYPOT_MARKER = '__HONEYPOT__'

    _MAJOR_PREFIXES = {
        'orange polska': 'Orange',
        'p4 ': 'Play',
        'polkomtel': 'Plus',
        't-mobile polska': 'T-Mobile',
    }

    def _is_major(name: str) -> bool:
        if not name:
            return False
        low = name.lower()
        return any(low.startswith(p) for p in _MAJOR_PREFIXES)

    major_providers = [p for p in providers if _is_major(p)]

    five_g_sites_by_op = (
        db.session.query(
            BaseStation.service_provider,
            func.count(distinct(BaseStation.location)),
        )
        .filter(BaseStation.service_provider != HONEYPOT_MARKER)
        .filter(BaseStation.frequency_band.like('5G%'))
        .group_by(BaseStation.service_provider).all()
    )
    five_g_coverage = {}
    for p in providers:
        total_sites = stats['physical_sites'].get(p, 0) or 0
        with_5g = dict(five_g_sites_by_op).get(p, 0)
        five_g_coverage[p] = {
            'sites_with_5g': int(with_5g),
            'total_sites': int(total_sites),
            'pct': round(100.0 * with_5g / total_sites, 1) if total_sites else 0.0,
        }


    top_cities_query = (
        db.session.query(
            BaseStation.city,
            func.count(distinct(BaseStation.location)).label('sites'),
        )
        .filter(BaseStation.service_provider != HONEYPOT_MARKER)
        .filter(BaseStation.city.isnot(None))
        .filter(BaseStation.city != '—')
        .group_by(BaseStation.city)
        .order_by(func.count(distinct(BaseStation.location)).desc())
        .limit(10).all()
    )
    top_cities = [
        {'city': city, 'sites': int(sites)}
        for (city, sites) in top_cities_query
    ]

    sites_per_generation = stats.get('sites_per_generation', {})
    avg_bands_per_site: dict = {}
    for p in providers:
        gens = generation_breakdown.get(p, {})
        sites = sites_per_generation.get(p, {})
        avg_bands_per_site[p] = {
            g: round(gens[g] / sites.get(g, 1), 2) if sites.get(g)
            else 0.0
            for g in generations
        }

    return {
        'physical_sites': stats['physical_sites'],
        'bands_data': bands_data,
        'providers': providers,
        'sorted_bands': sorted_bands,
        'band_totals': band_totals,
        'provider_totals': provider_totals,
        'generation_breakdown': generation_breakdown,
        'generation_totals': generation_totals,
        'generations': generations,
        'sites_per_generation': sites_per_generation,
        'avg_bands_per_site': avg_bands_per_site,
        'major_providers': major_providers,
        'five_g_coverage': five_g_coverage,
        'top_cities': top_cities,
        # Hero-strip top-level numbers.
        'grand_total_sites': sum(stats['physical_sites'].values()),
        'grand_total_entries': sum(provider_totals.values()),
    }
    
def get_all_stations():
    return BaseStation.query.all()