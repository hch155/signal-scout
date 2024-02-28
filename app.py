from flask import Flask, render_template, request, jsonify, session
from flask_session import Session
from models import db, BaseStation
from sqlalchemy import or_
from collections import defaultdict
from queries import get_all_stations, find_nearest_stations, process_stations, haversine, get_band_stats, get_stats
import markdown, os, random

app = Flask(__name__)

# Session configuration
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_COOKIE_SAMESITE"] = 'Strict'  # SameSite attribute for all session cookies
#app.config["SESSION_COOKIE_SECURE"] = True  # Only send cookies over HTTPS, to be implemented
app.config["SESSION_COOKIE_HTTPONLY"] = True  # Prevent JavaScript access to session cookie, prevent XSS scripting attacks

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stations.db'

# Flask extensions init
Session(app)
db.init_app(app)

@app.before_request # Ensure session changes are acknowledged and persisted by Flask
def session_handling():
    session.modified = True  # Inform the session it has been modified

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
    stats= get_stats()
    return render_template('stats.html', stats=stats)

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
        data = request.get_json()
        session['user_location'] = {'lat': data['lat'], 'lng': data['lng']} 
        user_lat = data['lat']
        user_lng = data['lng']
        limit = data.get('limit', 6)
        max_distance = data.get('max_distance', None)
        
        nearest_stations = find_nearest_stations(user_lat, user_lng, limit=limit, max_distance=max_distance)
        #print("Extracted nearest_stations", nearest_stations)
        #print(f"Data type nearest_stations: {type(nearest_stations)}")
        
        if nearest_stations is None or not nearest_stations.get('stations'): # If the key 'stations' does not exist, .get() returns None by default, if faulty (e.g empty list) None or False
            print("No stations found or an error occurred")
            return jsonify({'error': 'No stations found or an error occurred'}), 500
        return jsonify(nearest_stations)

    except Exception as e:
        print(f"Error in submit_location: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stations', methods=['GET'])
def get_stations():
    try:
        user_location = session.get('user_location')
        if user_location:
            user_lat = user_location['lat']
            user_lng = user_location['lng']
        else:
            return jsonify({"error": "User location not set"}), 400

        max_distance = request.args.get('max_distance', default=None, type=float)
        limit = request.args.get('limit', default=6, type=int)
        frequency_bands = request.args.getlist('frequency_bands')
        selected_service_provider = request.args.getlist('service_provider')
        selected_service_provider= []
        for provider in selected_service_provider:
            if provider == "P4 Sp. z o.o.'":
                provider = provider.rstrip("'")
                selected_service_provider.append(provider)        
            else:
                selected_service_provider = None

        result = find_nearest_stations(user_lat, user_lng, max_distance=max_distance, limit=limit)
        stations = result.get("stations", [])
        stations_count = result.get("count", 0)

        if frequency_bands:
            stations = [station for station in stations if set(frequency_bands).issubset(set(station['frequency_bands']))]

        if selected_service_provider:
            stations = [station for station in stations if station['service_provider'] == selected_service_provider]

        stations_data = [{
            'basestation_id': station['basestation_id'], 
            'latitude': station['latitude'],              
            'longitude': station['longitude'],            
            'frequency_bands': station['frequency_bands'], 
            'city': station['city'],                     
            'location': station['location'],              
            'service_provider': station['service_provider'],
            'distance': station['distance']
        } for station in stations]

        filtered_count = len(stations_data)

        return jsonify({"stations": stations_data, "count": filtered_count})

    except Exception as e:
        # Log the error for debugging
        print(f"Error fetching stations: {str(e)}")
        return jsonify({"error": "An error occurred while fetching stations."}), 500

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ['true', '1', 't']
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=debug_mode, host='0.0.0.0', port=port)