from flask import Flask, render_template, request, jsonify, session
from flask_bcrypt import Bcrypt
from flask_session import Session
from database import db
from models import BaseStation, User
from sqlalchemy import or_
from collections import defaultdict
from queries import get_all_stations, find_nearest_stations, process_stations, haversine, get_band_stats, get_stats
from dotenv import load_dotenv
from datetime import timedelta
import markdown, os, random, re

app = Flask(__name__)
bcrypt = Bcrypt(app)
load_dotenv()
# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stations.db'
app.config['SQLALCHEMY_BINDS'] = {
    'users': 'sqlite:///users.db' 
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
with app.app_context():
    db.create_all()
    
"""
if os.getenv('ENV') == 'production':
    app.config['SQLALCHEMY_BINDS'] = {
        'users': os.getenv('COCKROACH_DB_URI')
    }
else:
    app.config['SQLALCHEMY_BINDS'] = {
        'users': 'sqlite:///./instance/users.db'
    }
"""

# HTTPS encryption for Flask

ssl_context = (os.getenv('SSL_CERT_PATH'), os.getenv('SSL_KEY_PATH'))

# Session configuration

app.config["SESSION_PERMANENT"] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_COOKIE_SAMESITE"] = 'Lax'  # SameSite attribute for all session cookies
app.config["SESSION_COOKIE_SECURE"] = True  # Only send cookies over HTTPS
app.config["SESSION_COOKIE_HTTPONLY"] = True  # Prevent JavaScript access to session cookie, prevent XSS scripting attacks
Session(app)

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

def get_html_content_from_markdown(file_name):

    if os.environ.get('ENV') == 'PRODUCTION':
        base_path = 'src/content'
    else:
        base_path = 'content'

    file_path = os.path.join(base_path, file_name)

    with open(file_path, 'r') as file:
        markdown_content = file.read()
    html_content = markdown.markdown(markdown_content)

    return html_content

@app.route('/data')
def data_page():
    html_content = get_html_content_from_markdown('data.md')
    return render_template('data.html', content=html_content)

@app.route('/stats')
def stats_page():
    stats= get_stats()
    return render_template('stats.html', stats=stats)

@app.route('/tips')
def tips_page():
    file_name = 'tips_registered.md' if 'user_id' in session else 'tips.md'
    html_content = get_html_content_from_markdown(file_name)
    return render_template('tips.html', content=html_content)

@app.route('/tips/content')
def tips_content():
    file_name = 'tips_registered.md' if 'user_id' in session else 'tips.md'
    html_content = get_html_content_from_markdown(file_name)
    return html_content

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
        limit = data.get('limit', 9)
        max_distance = data.get('max_distance', None)
        
        nearest_stations = find_nearest_stations(user_lat, user_lng, limit=limit, max_distance=max_distance)
        
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
        user_lat = request.args.get('lat')
        user_lng = request.args.get('lng')
        
        if user_lat and user_lng:    
            user_lat = float(user_lat)
            user_lng = float(user_lng)
        else:
            user_location = session.get('user_location')
            if user_location:
                user_lat = user_location['lat']
                user_lng = user_location['lng']
            else:
                return jsonify({"error": "User location not set"}), 400

        max_distance = request.args.get('max_distance', default=None, type=float)
        limit = request.args.get('limit', default=9, type=int)
        frequency_bands = request.args.getlist('frequency_bands')
        raw_service_providers = request.args.getlist('service_provider')

        cleaned_service_providers = [provider.rstrip("'") for provider in raw_service_providers]

        result = find_nearest_stations(user_lat, user_lng, max_distance=max_distance, limit=limit, service_providers=cleaned_service_providers, frequency_bands=frequency_bands)
        stations = result.get("stations", [])
        stations_count = result.get("count", 0)

        if frequency_bands:
            stations = [station for station in stations if set(frequency_bands).issubset(set(station['frequency_bands']))]

        if cleaned_service_providers:
            stations = [station for station in stations if station['service_provider'] in cleaned_service_providers]

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

@app.route('/find_station', methods=['GET'])
def find_station():
    basestation_id = request.args.get('basestation_id', type=str)
    if not basestation_id or len(basestation_id) > 7 or not re.match("^[A-Za-z0-9]+$", basestation_id):
        return jsonify({"error": "Request cannot be processed"}), 400

    station = BaseStation.query.filter_by(basestation_id=basestation_id).first()
    if station:
        station_data = {
            'basestation_id': station.basestation_id,
            'latitude': station.latitude,
            'longitude': station.longitude,
            'frequency_bands': station.frequency_band,
            'city': station.city,
            'location': station.location,
            'service_provider': station.service_provider,
        }
        return jsonify(station_data)
    else:
        return jsonify({"error": "Station not found"}), 404

@app.route('/register', methods=['POST'])
def register_user():
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return "Invalid email address.", 400

    if not re.fullmatch(r"(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*\W).{8,}$", password):
        return "Password does not meet criteria.", 400

    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match.'}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user is not None:
        return 'Email already registered.'

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
 
    try:    
        user = User(email=email, password_hash=hashed_password)
        db.session.add(user)
        db.session.commit()
        return jsonify({"success": True, "message": "User registered successfully."}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error registering user: {e}")
        return jsonify({"success": False, "message": "Registration failed due to a server error."}), 500
    
@app.route('/login', methods=['POST'])
def login_user():
    email = request.form.get('email')
    password = request.form.get('password')
 
    user = User.query.filter_by(email=email).first()

    if user and bcrypt.check_password_hash(user.password_hash, password):
        session['user_id'] = user.id
        return jsonify({"success": True, "message": "Logged in successfully."}), 200
    else:
        return jsonify({"success": False, "message": "Invalid email or password."}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None) 
    return jsonify({"success": True, "message": "You have been logged out."}), 200


@app.route('/session_check')
def session_check():
    is_logged_in = 'user_id' in session
    return jsonify({"logged_in": is_logged_in})

@app.route('/debug_session')
def debug_session():
    session_info = {
        "logged_in": 'user_id' in session,
        "session_permanent": session.permanent,
        "session_lifetime": str(app.permanent_session_lifetime),
    }
    return jsonify(session_info)

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ['true', '1', 't']
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=debug_mode,
            host='0.0.0.0',
            port=port)
            #ssl_context=('/etc/ssl/localcerts/localhost+2.pem', '/etc/ssl/localcerts/localhost+2-key.pem')) #app.config["SESSION_COOKIE_SECURE"] = True
