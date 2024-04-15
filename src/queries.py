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

def sort_frequency_bands(bands):
    def get_sort_key(band):
        # Define sorting priority
        if band.startswith('5G'):
            priority = 1
        elif 'LTE' in band:
            priority = 2
        elif band.endswith('GSM'):
            priority = 3
        else:
            priority = 4 

        numeric_part = int(''.join(filter(str.isdigit, band))) if any(char.isdigit() for char in band) else 0
        return (priority, -numeric_part, band)  # Sort by priority, then by negative numeric part, then by band name

    return sorted(bands, key=get_sort_key)

def get_latitude_segment(latitude):
    """Returns the segment index for a given latitude."""
    base_latitude = 49.0  # Starting latitude
    segment_size = 0.3  # Size of each latitude segment // 33.333 km
    return int((latitude - base_latitude) / segment_size)

def find_nearest_stations(user_lat, user_lng, limit=9, max_distance=None, service_providers=[], frequency_bands=[]):
    user_segment = get_latitude_segment(user_lat)
    adjacent_segments = [user_segment - 1, user_segment, user_segment + 1]  # Include boundary segments

    try:
        # Filter early in the query to reduce memory usage and processing time
        query = BaseStation.query.filter(BaseStation.latitude_segment.in_(adjacent_segments))
        
        if service_providers:
            query = query.filter(BaseStation.service_provider.in_(service_providers))
        if frequency_bands:
            query = query.filter(BaseStation.frequency_band.in_(frequency_bands))
        
        # Execute the filtered query
        filtered_stations = query.all()

        # Initialize a dictionary to hold the grouped stations with aggregated frequency bands
        grouped_stations = {}

        # Combine filtering by max_distance and grouping into a single loop
        for station in filtered_stations:
            distance = haversine(user_lat, user_lng, station.latitude, station.longitude)
            
            if max_distance is not None and distance > max_distance:
                continue  # Skip this station if it's beyond the max_distance
            
            # Key for grouping stations by their unique location
            key = (station.latitude, station.longitude)
            distance_rounded = round(distance, 2)
            
            # Aggregate frequency bands and update distance if necessary
            if key not in grouped_stations:
                grouped_stations[key] = {
                    'basestation_id': station.basestation_id,  
                    'city': station.city,
                    'service_provider': station.service_provider,                      
                    'location': station.location,              
                    'latitude': station.latitude,
                    'longitude': station.longitude,
                    'frequency_bands': {station.frequency_band},
                    'distance': distance_rounded
                }
            else:
                # Add the current station's frequency band to the set
                grouped_stations[key]['frequency_bands'].add(station.frequency_band)
                # Ensure the stored distance is the minimum distance to this location
                if distance_rounded < grouped_stations[key]['distance']:
                    grouped_stations[key]['distance'] = distance_rounded
        
        for station_info in grouped_stations.values():
            # Sort the frequency bands
            sorted_bands = sort_frequency_bands(station_info['frequency_bands'])
            station_info['frequency_bands'] = sorted_bands

        final_stations_list = sorted(grouped_stations.values(), key=lambda x: x['distance'])

        # Prepare the final list of stations, applying the limit
        final_stations_list = sorted(grouped_stations.values(), key=lambda x: x['distance'])
        if limit is not None:
            final_stations_list = final_stations_list[:limit]

        # Convert frequency_bands sets to lists for JSON serialization
        for station_info in final_stations_list:
            station_info['frequency_bands'] = list(station_info['frequency_bands'])

        return {"stations": final_stations_list, "count": len(final_stations_list)}

    except Exception as e:
        print(f"Error in find_nearest_stations: {e}")
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