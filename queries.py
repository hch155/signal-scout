from models import BaseStation, db

def find_nearest_stations(user_lat, user_lon, limit=5):
    # find and return the nearest stations

    nearest_stations = BaseStation.query \
        .order_by(BaseStation.latitude, BaseStation.longitude) \
        .limit(limit) \
        .all()
    return nearest_stations

def get_all_stations():
    return BaseStation.query.all()