from flask import Flask, render_template, request, jsonify
from queries import get_all_stations, find_nearest_stations

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stations.db'
db.init_app(app)

@app.route('/')
def index():
    return render_template('map.html') # Render the map view

@app.route('/submit_location', methods=['POST'])
def submit_location():
    data = request.json
    latitude = data['lat']
    longitude = data['lng']
    # Process the location data...
    return 'Location Received', 200


def submit_location():
    data = request.json
    nearest_stations = find_nearest_stations(data['lat'], data['lng'])

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
