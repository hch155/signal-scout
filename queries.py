import math
from models import BaseStation, db
from sqlalchemy import func, distinct
from collections import Counter, defaultdict

def haversine(lat1, lon1, lat2, lon2):
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    r = 6371  # Radius of earth in kilometers
    return c * r

def find_nearest_stations(user_lat, user_lon, limit=6, max_distance=None):
    try:
        stations = BaseStation.query.all()
        station_details = {}

        for station in stations:
            distance = haversine(user_lat, user_lon, station.latitude, station.longitude)
            key = station.basestation_id

            if key not in station_details:
                station_details[key] = {
                    'station': station,
                    'distance': distance,
                    'frequency_bands': set()
                }
            station_details[key]['frequency_bands'].add(station.frequency_band)

            if distance < station_details[key]['distance']:
                station_details[key]['distance'] = distance

        stations_with_distance = list(station_details.values())
        if max_distance is not None:
            stations_with_distance = [detail for detail in stations_with_distance if detail['distance'] <= max_distance]
            for detail in stations_with_distance:  # Debugging distance filtering
                 print(f"Included station {detail['station'].basestation_id} at distance: {detail['distance']} km")

        stations_with_distance.sort(key=lambda x: x['distance'])

        if max_distance is None:
            stations_with_distance = stations_with_distance[:limit]

        closest_stations = []
        for detail in stations_with_distance:
            station = detail['station']
            closest_stations.append({
                'basestation_id': station.basestation_id,  
                'city': station.city,
                'service_provider': station.service_provider,                      
                'location': station.location,              
                'latitude': station.latitude,
                'longitude': station.longitude,
                'frequency_bands': list(detail['frequency_bands']),
                'distance': round(detail['distance'], 2)
            })

        return closest_stations

    except Exception as e:
        print(f"Error in find_nearest_stations: {e}")
        return []  # 

def process_stations(stations):
    grouped_stations = {}

    for station in stations:
        key = (station.latitude, station.longitude)
        if key not in grouped_stations:
            grouped_stations[key] = {
                'basestation_id': station.basestation_id,  
                'city': station.city,
                'service_provider': station.service_provider,                      
                'location': station.location,
                'latitude': station.latitude,
                'longitude': station.longitude,
                'frequency_bands': set()
            }
        grouped_stations[key]['frequency_bands'].add(station.frequency_band)

    # Convert sets to lists for JSON serialization
    for key in grouped_stations:
        grouped_stations[key]['frequency_bands'] = list(grouped_stations[key]['frequency_bands'])

    return list(grouped_stations.values())

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

def get_all_stations():
    return BaseStation.query.all()