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

def find_nearest_stations(user_lat, user_lon, limit=9, max_distance=None, service_providers=[], frequency_bands=[]):
    try:
        stations = BaseStation.query.all()
        stations_with_distance = []

        for station in stations:
            if service_providers and station.service_provider not in service_providers:
                continue
            if frequency_bands and station.frequency_band not in frequency_bands:
                continue 
                     
            distance = haversine(user_lat, user_lon, station.latitude, station.longitude)
            if max_distance is None or distance <= max_distance:
                stations_with_distance.append((station, distance))

        stations_with_distance.sort(key=lambda x: x[1])

        # Prepare for grouping stations with unique location
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
                    'frequency_bands': {station.frequency_band},  # Set for aggregating frequency bands
                    'distance': distance_rounded
                }
            else:
                grouped_stations[key]['frequency_bands'].add(station.frequency_band)
                # Update distance if a closer station with the same coordinates is found
                if distance_rounded < grouped_stations[key]['distance']:
                    grouped_stations[key]['distance'] = distance_rounded

        # Convert frequency_bands set to list for JSON serialization
        for station_info in grouped_stations.values():
            station_info['frequency_bands'] = list(station_info['frequency_bands'])

        # Apply limit if max_distance is not specified        
        closest_stations = list(grouped_stations.values())
 
        if limit is not None and max_distance is None:
            closest_stations = closest_stations[:int(limit)]
        stations_count = len(closest_stations)
        
        return {"stations": closest_stations, "count": stations_count}


    except Exception as e:
        print(f"Error in find_nearest_stations: {e}")
        return {"stations": [], "count": 0}  



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

def get_stats():
    stats = get_band_stats()
    band_order = ['5G3600', '5G2600', '5G2100', '5G1800', 'LTE2600', 'LTE2100', 'LTE1800', 'LTE900', 'LTE800', 'GSM900']
    
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