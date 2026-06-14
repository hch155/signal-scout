import math
import logging
import os
import sqlite3
from datetime import datetime
from models import BaseStation, db
from sqlalchemy import func, distinct, case

logger = logging.getLogger(__name__)


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


# PR #47: per-band "poor coverage" thresholds in km. Values come from
# frequencyRanges in static/scripts/pages/ui-interactions.js — the same
# constants the on-map signal-strength legend uses, so the UI and API
# agree on what "dead" means. High-band (5G3600, LTE2600) drops off
# fast; low-band (L800, L900, GSM900) penetrates much further.
#
# Bands not in this map fall back to DEFAULT_GAP_THRESHOLD_KM (3 km
# = the mid-band poor-tier).
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
# Search this many ±0.1° lat segments around the user. ~3 segments
# ≈ 33 km — wide enough to catch a low-band station even if the user
# is in the middle of nowhere; not so wide it scans the whole country.
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
        # PR #47.4: pull the full BTS row (provider, basestation_id,
        # city, location) — not just the band+coords — so the band-click
        # UI can open a real Leaflet popup + sidebar card without a
        # second round-trip per click.
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
        ).all()
    except Exception as e:
        logger.error(f"Error in find_coverage_gaps query: {e}")
        return {"gaps": [], "summary": {"total_bands": 0, "covered": 0, "dead": 0}}

    # PR #47.3: also remember WHICH BTS is the nearest, so the UI can
    # highlight that single station on the map when the user clicks a
    # band. Storing only the distance was enough for the ✓/✗ verdict
    # but not for "show me where it is".
    nearest_per_band: dict[str, dict] = {}
    # PR #47.4: index every (lat, lng, provider) location → set of bands,
    # so we can later answer "what other bands does the nearest BTS
    # carry?" without re-querying. Keys quantised to 6 decimal places
    # to dodge float-equality landmines.
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
    # Sort by the same priority the rest of the UI uses (5G first,
    # then LTE, UMTS, GSM) so the response feels consistent with the
    # popup / sidebar ordering.
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
    user_segment = get_latitude_segment(user_lat)
    adjacent_segments = [user_segment - 1, user_segment, user_segment + 1]

    try:
        # GROUP BY in SQL with GROUP_CONCAT to aggregate frequency bands
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
    # Honeypot rows in BaseStation (audit fix L-NEW-4) carry the
    # service_provider = '__HONEYPOT__' marker so legitimate
    # statistics don't get polluted — and so a scraper can't tell
    # how many honeypot rows we planted by diffing the totals.
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

    # 2026-04-28: distinct-site count per (provider, generation prefix).
    # Crucial for the /stats UI because raw "entries" inflates LTE
    # (1 site usually broadcasts 4-6 LTE bands; 5G typically 1-3),
    # giving a misleading "LTE dominates" impression. Sites-per-
    # generation is the closest single-query approximation of real
    # coverage. Same honeypot filter.
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

    # Derived aggregates for the upgraded /stats UI. Cheap (already
    # have the per-(band,provider) counts in memory) — keeps the
    # template free of arithmetic + makes the same numbers reusable
    # for an API endpoint later if we add one.
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
    # Per-(provider, generation) breakdown for the "5G vs LTE vs ..."
    # bar chart at the top. {provider: {'5G': N, 'LTE': N, 'UMTS': N,
    # 'GSM': N}}.
    generations = ['5G', 'LTE', 'UMTS', 'GSM']
    generation_breakdown: dict = {p: {g: 0 for g in generations} for p in providers}
    for band in sorted_bands:
        gen = _gen_of(band)
        if gen not in generations:
            continue
        for p in providers:
            generation_breakdown[p][gen] += bands_data[band].get(p, 0)
    # Per-generation aggregate (across all providers) for the hero
    # strip "5G coverage by generation" line.
    generation_totals = {
        g: sum(generation_breakdown[p][g] for p in providers)
        for g in generations
    }

    # 2026-04-28: telco-grade KPIs — what real operators / equipment
    # vendors track in their network monitoring dashboards.
    HONEYPOT_MARKER = '__HONEYPOT__'

    # 2026-04-29: only the four major Polish MNOs make sense in the
    # KPI panels. Tiny outfits like Tatrzańskie Ochotnicze Pogotowie
    # Ratunkowe (mountain rescue, 3 sites) leak into the providers
    # list and made the "5G race" / "legacy debt" panels look noisy.
    # UKE also publishes both upper- and lower-case spellings of the
    # same legal entity ("P4 sp. z o.o." vs "P4 Sp. z o.o.") across
    # months — match on a normalized lower-cased prefix and pick the
    # variant actually present in this snapshot, so we don't ship
    # double rows.
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

    # 1) 5G race tracker: % of operator's sites with at least one 5G
    #    band. Same shape RAN vendors publish in quarterly investor
    #    decks ("X of our customer's sites are 5G-enabled").
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

    # 2026-04-29: dropped both legacy debt KPIs (was "GSM-only" — always
    # 0 across all 4 PL MNOs because they've all overlay-upgraded; then
    # "no-5G" — but with three of four operators already at <7%, the
    # panel was just visual clutter and the broken Polkomtel data
    # rendered as a nonsense 99% bar). 5G race tracker above already
    # shows the inverse, formatted as the positive KPI users actually
    # want to see.

    # 2026-04-29: dropped the "Network sharing (co-located sites)" KPI.
    # Grouped on EXACT BaseStation.location string, but real PL operators
    # log shared towers under slightly different addresses (different
    # building numbers, varying punctuation, language case), so the
    # 3.2% number was an order of magnitude too low — Plus + Play do
    # active RAN sharing in rural areas at ~50% of their fleet.
    # Honest fix would be lat/lng-radius bucketing (e.g. round to 4dp,
    # group within ~10m); deferred until we have time to validate
    # against an external source (UKE doesn't publish a sharing field).

    # 4) Top 10 cities by total physical sites — most-built-out
    #    metro areas. Standard geographic-distribution panel.
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
    # Average bands per site per (provider, generation) — derived
    # context that explains why "LTE entries" inflates relative to
    # "5G entries". A real site usually broadcasts 4-6 LTE bands but
    # only 1-3 5G bands. avg = entries / sites; rounded to 2 dp.
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
        # Telco KPIs (2026-04-28). KPI panels render only the four
        # majors (Orange / Play / Plus / T-Mobile) — see major_providers
        # filter. Full bands table below still shows everything.
        'major_providers': major_providers,
        'five_g_coverage': five_g_coverage,
        'top_cities': top_cities,
        # Hero-strip top-level numbers.
        'grand_total_sites': sum(stats['physical_sites'].values()),
        'grand_total_entries': sum(provider_totals.values()),
    }
    
def get_all_stations():
    return BaseStation.query.all()