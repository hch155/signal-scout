from flask import Flask, render_template, request, jsonify
from models import db, BaseStation
from queries import get_all_stations, find_nearest_stations


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stations.db'
db.init_app(app)


@app.route('/')
def index():
    return render_template('map.html') # Render the map view

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')


@app.route('/submit_location', methods=['POST'])
def submit_location():
    try:
        data = request.json
        nearest_stations = find_nearest_stations(data['lat'], data['lng'])
        if nearest_stations is None:
            print("No stations found or an error occurred")
            return jsonify({'error': 'No stations found or an error occurred'}), 500

        stations_data = [{
            'basestation_id': station['basestation_id'],
            'city': station['city'],
            'location': station['location'],
            'service_provider': station['service_provider'],
            'latitude': station['latitude'],
            'longitude': station['longitude'],
            'frequency_bands': station['frequency_bands']
        } for station in nearest_stations]

        return jsonify(stations_data)

    except Exception as e:
        print(f"Error in submit_location: {e}")
        return jsonify({'error': str(e)}), 500



def stations():
    all_stations = get_all_stations()
    stations_data = [{ 
                      'basestation_id': station.basestation_id, 
                      'latitude': station.latitude,              
                      'longitude': station.longitude,            
                      'frequency_bands': station.frequency_band, 
                      'city': station.city,                     
                      'location': station.location,              
                      'service_provider': station.service_provider  
                    } for station in all_stations]

    return jsonify(stations_data)

@app.route('/stations', methods=['GET'])
def get_stations():
    all_stations = get_all_stations()
    stations_data = [{
                      'basestation_id': station.basestation_id, 
                      'latitude': station.latitude,              
                      'longitude': station.longitude,            
                      'frequency_bands': station.frequency_band, 
                      'city': station.city,                     
                      'location': station.location,              
                      'service_provider': station.service_provider 
                    } for station in all_stations]

    return jsonify(stations_data)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0') # useful for development, remember to turn off debug mode in production as it can expose sensitive information.
                                        # host='0.0.0.0' so it is accessible from your host machine or external requests.
