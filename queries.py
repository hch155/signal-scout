import math
from models import BaseStation, db

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

def find_nearest_stations(user_lat, user_lon, limit=5):
    try:
        stations = BaseStation.query.all()
        stations_with_distance = []

        for station in stations:
            distance = haversine(user_lat, user_lon, station.latitude, station.longitude)
            stations_with_distance.append((station, distance))

        # sorting stations by distance, reorders the tuples in the stations_with_distance list so that they are sorted from the nearest station 
        stations_with_distance.sort(key=lambda x: x[1])

        # getting the closest limit no. of stations
        closest_stations = [station for station, distance in stations_with_distance[:limit]]

        return closest_stations
    except Exception as e:
        print(f"Error in find_nearest_stations: {e}")
        return []  # Return an empty list in case of an error


    # Assuming nearest_stations is a list of station objects
def process_stations(stations):
    grouped_stations = {}

    for station in stations:
        key = (station.latitude, station.longitude)
        if key not in grouped_stations:
            grouped_stations[key] = {
                'latitude': station.latitude,
                'longitude': station.longitude,
                'frequency_bands': set()
            }
        grouped_stations[key]['frequency_bands'].add(station.frequency_band)

    # Convert sets to lists for JSON serialization
    for key in grouped_stations:
        grouped_stations[key]['frequency_bands'] = list(grouped_stations[key]['frequency_bands'])

    return list(grouped_stations.values())
          
def get_all_stations():
    return BaseStation.query.all()