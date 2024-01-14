from flask import Flask, render_template, request, jsonify
from models import db
from queries import get_all_stations, find_nearest_stations


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stations.db'
db.init_app(app)

@app.route('/')
def index():
    return render_template('map.html') # Render the map view

@app.route('/submit_location', methods=['POST'])
def submit_location():
    try:
        data = request.json

        # Validating input data
        if not data or 'lat' not in data or 'lng' not in data:
            abort(400, description="Missing latitude or longitude data.")

        latitude = data['lat']
        longitude = data['lng']

        # Additional validation for latitude and longitude
        if not isinstance(latitude, (float, int)) or not isinstance(longitude, (float, int)):
            abort(400, description="Invalid latitude or longitude format.")

        # Database query wrapped in try-except for error handling
        try:
            nearest_stations = find_nearest_stations(latitude, longitude)
        except Exception as e:
            # Log this exception for debugging
            print(f"Database query error: {e}")
            abort(500, description="Internal server error.")

        # Format and return the response data
        stations_data = [{
            'id': station.id,
            'latitude': station.latitude,
            'longitude': station.longitude,
            'frequency_band': station.frequency_band
        } for station in nearest_stations]

        return jsonify(stations_data)

    except Exception as e:
        # Log unexpected exceptions for debugging
        print(f"Unexpected error: {e}")
        abort(500, description="Internal server error.")


def submit_location():
    data = request.json
    nearest_stations = find_nearest_stations(data['lat'], data['lng'])
    processed_stations = process_stations(nearest_stations)

def stations():
    all_stations = get_all_stations()
    stations_data = [{'id': station.id, 'latitude': station.latitude, 'longitude': station.longitude, 'frequency_band': station.frequency_band} for station in all_stations]
    return jsonify(stations_data)

@app.route('/stations', methods=['GET'])
def stations():
    all_stations = get_all_stations()
    stations_data = [{'id': station.id, 'latitude': station.latitude, 'longitude': station.longitude, 'frequency_band': station.frequency_band} for station in all_stations]
    return jsonify(stations_data)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0') # useful for development, remember to turn off debug mode in production as it can expose sensitive information.
                                        # host='0.0.0.0' so it is accessible from your host machine or external requests.
