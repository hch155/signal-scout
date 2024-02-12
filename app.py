from flask import Flask, render_template, request, jsonify
from models import db, BaseStation
from queries import get_all_stations, find_nearest_stations, haversine, get_band_stats
import markdown, os, random

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stations.db'
db.init_app(app)

SLOGANS = [
    ("On the Move?", "Navigate to the Nearest Base Stations for Uninterrupted Connectivity!"),
    ("Seeking Signal?", "Discover the Closest Connectivity Points for Seamless Communication!"),
    ("Chasing Coverage?", "Pinpoint the Best Signal Sources for Flawless Connections!"),
    ("Stay Connected Everywhere", "Discover the Closest Base Stations for Optimal Signal Strength!")
]

@app.route('/')
def home():
    slogan_title, slogan_text = random.choice(SLOGANS)
    return render_template('map.html', slogan_title=slogan_title, slogan_text=slogan_text)

@app.route('/data')
def data_page():
    with open('content/data.md', 'r') as file:
        content = file.read()
    html_content = markdown.markdown(content)
    return render_template('data.html', content=html_content)

@app.route('/stats')
def stats_page():
    return render_template('stats.html')

@app.route('/tips')
def tips_page():
    with open('content/tips.md', 'r') as file:
        content = file.read()
    html_content = markdown.markdown(content)
    return render_template('tips.html', content=html_content)    

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')


@app.route('/submit_location', methods=['POST'])
def submit_location():
    try:
        data = request.json
        user_lat = data['lat']
        user_lng = data['lng']
        nearest_stations = find_nearest_stations(user_lat, user_lng)
        
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
            'frequency_bands': station['frequency_bands'],
            'distance': station['distance']
        } for station in nearest_stations]

        return jsonify(stations_data)

    except Exception as e:
        print(f"Error in submit_location: {e}")
        return jsonify({'error': str(e)}), 500

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

@app.route('/get-stats')
def get_stats():
    stats = get_band_stats()
    band_order = ['5G3600', '5G2600', '5G2100', '5G1800', 'LTE2600', 'LTE2100', 'LTE1800', 'LTE900', 'LTE800', 'GSM900']
    def band_sort_key(band):
        if band in band_order:
            return band_order.index(band)
        return len(band_order)  # Place unknown bands at the end

    sorted_bands = sorted(stats['bands_data'].keys(), key=band_sort_key)

    return jsonify({
        'physical_sites': stats['physical_sites'],
        'bands_data': stats['bands_data'],
        'providers': stats['providers'],
        'sorted_bands': sorted_bands
    })

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ['true', '1', 't']
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=debug_mode, host='0.0.0.0', port=port)