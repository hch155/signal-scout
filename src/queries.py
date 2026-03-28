import math
import logging
from models import BaseStation, db
from sqlalchemy import func, distinct

logger = logging.getLogger(__name__)

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
    # Query for physical site counts per provider
    physical_sites_query = db.session.query(
        BaseStation.service_provider, 
        func.count(distinct(BaseStation.location))
    ).group_by(BaseStation.service_provider).all()

    # Query for band counts per provider
    band_counts_query = db.session.query(
        BaseStation.service_provider, 
        BaseStation.frequency_band,
        func.count(BaseStation.frequency_band)
    ).group_by(BaseStation.service_provider, BaseStation.frequency_band).all()

    # Organize data
    providers = set()
    bands_data = {}
    for provider, band, count in band_counts_query:
        providers.add(provider)
        if band not in bands_data:
            bands_data[band] = {}
        bands_data[band][provider] = count

    return {
        'physical_sites': dict(physical_sites_query),
        'bands_data': bands_data,
        'providers': sorted(providers)
    }

def get_stats():
    stats = get_band_stats()
    band_order = ['5G3600', '5G2100', '5G1800', '5G700', 'LTE2600', 'LTE2100', 'LTE1800', 'LTE900', 'LTE800', 'LTE700', 'UMTS2100', 'UMTS900', 'GSM1800', 'GSM900']
    
    def band_sort_key(band):
        if band in band_order:
            return band_order.index(band)
        return len(band_order)  # Place unknown bands at the end

    sorted_bands = sorted(stats['bands_data'].keys(), key=band_sort_key)

    return {
        'physical_sites': stats['physical_sites'],
        'bands_data': stats['bands_data'],
        'providers': stats['providers'],
        'sorted_bands': sorted_bands
    }
    
def get_all_stations():
    return BaseStation.query.all()