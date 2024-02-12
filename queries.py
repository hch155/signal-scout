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

def find_nearest_stations(user_lat, user_lon, limit=6):
    try:
        stations = BaseStation.query.all()
        stations_with_distance = []

        for station in stations:
            distance = haversine(user_lat, user_lon, station.latitude, station.longitude)
            stations_with_distance.append((station, distance))

        # Sort stations by distance, reorders the tuples in the stations_with_distance list so that they are sorted from the nearest station 
        stations_with_distance.sort(key=lambda x: x[1])

        # Group by location and aggregate frequency bands
        grouped_stations = {}
        for station, distance in stations_with_distance:
            key = (station.latitude, station.longitude)
            distance_rounded = round(distance, 2)

            if key not in grouped_stations:
                grouped_stations[key] = {
                    'basestation_id': station.basestation_id,  
                    'city': station.city,
                    'service_provider': station.service_provider,                      
                    'location': station.location,              
                    'latitude': station.latitude,
                    'longitude': station.longitude,
                    'frequency_bands': set(),
                    'distance': distance_rounded
                }
            else:
                if distance_rounded < grouped_stations[key]['distance']:
                    grouped_stations[key]['distance'] = distance_rounded

            grouped_stations[key]['frequency_bands'].add(station.frequency_band)
            
        # Convert to list and limit the results
        closest_stations = list(grouped_stations.values())[:limit]
        
        # Convert sets to lists for JSON serialization
        for station in closest_stations:
            station['frequency_bands'] = list(station['frequency_bands'])

        return closest_stations
    except Exception as e:
        print(f"Error in find_nearest_stations: {e}")
        return []  # Return an empty list in case of an error

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