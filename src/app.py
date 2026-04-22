from flask import Flask, render_template, request, jsonify, session
from flask_bcrypt import Bcrypt
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from database import db
from models import BaseStation, User
from sqlalchemy import or_
from queries import get_all_stations, find_nearest_stations, haversine, get_band_stats, get_stats
from observability import (
    init_observability,
    csrf_failures_total,
    login_failures_total,
    rate_limit_hits_total,
    station_search_total,
    empty_result_total,
    provider_filter_used_total,
    band_filter_used_total,
    requests_by_user_agent_class_total,
    classify_user_agent,
)
from dotenv import load_dotenv
from datetime import timedelta
import markdown, os, random, re, logging, secrets

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000 if os.getenv('ENV') == 'PRODUCTION' else 0
bcrypt = Bcrypt(app)
logging.basicConfig(level=logging.INFO)

# Database configuration

basedir = os.path.abspath(os.path.dirname(__file__))
stations_db_path = os.getenv(
    'STATIONS_DB_PATH', os.path.join(basedir, 'instance', 'stations.db')
)
users_db_path = os.getenv(
    'USERS_DB_PATH', os.path.join(basedir, 'instance', 'users.db')
)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{stations_db_path}'
app.config['SQLALCHEMY_BINDS'] = {
    'users': f'sqlite:///{users_db_path}'
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
with app.app_context():
    db.create_all()

# HTTPS encryption for Flask


# Session configuration

app.config["SESSION_PERMANENT"] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_COOKIE_SAMESITE"] = 'Lax'  # SameSite attribute for all session cookies
# Secure cookie only over HTTPS in production. On http://localhost the
# Secure flag drops the cookie entirely, which would block CSRF flow during
# local dev / perf tests. Production env sets ENV=PRODUCTION (cd.yaml).
app.config["SESSION_COOKIE_SECURE"] = os.getenv('ENV') == 'PRODUCTION'
app.config["SESSION_COOKIE_HTTPONLY"] = True  # Prevent JavaScript access to session cookie, prevent XSS scripting attacks
Session(app)

limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["16 per minute"])

# Wire Prometheus exporter (/metrics with bearer-token auth) and /healthz.
init_observability(app)

@app.errorhandler(429)
def rate_limit_exceeded(e):
    rate_limit_hits_total.labels(endpoint=request.endpoint or "unknown").inc()
    return '<html><body><h1>Rate Limit Exceeded</h1><p>Please wait a minute before making new requests.</p><img src="/static/limitexceededfresh.png" alt="Rate Limit Exceeded"></body></html>', 429

def _build_csp_policy() -> str:
    """CSP composed at startup so the Plausible host (env-driven) is allowed
    in script-src + connect-src only when configured. Keeps the CSP strict
    by default and avoids opening allowances no one is using."""
    plausible_url = os.getenv('PLAUSIBLE_SCRIPT_URL', '').strip()
    plausible_origin = ''
    if plausible_url:
        # Trim path/query to leave just scheme+host for CSP.
        from urllib.parse import urlparse
        parsed = urlparse(plausible_url)
        if parsed.scheme and parsed.netloc:
            plausible_origin = f"{parsed.scheme}://{parsed.netloc}"

    script_extras = ' ' + plausible_origin if plausible_origin else ''
    connect_extras = ' ' + plausible_origin if plausible_origin else ''

    return (
        "default-src 'self'; "
        f"script-src 'self' https://cdn.jsdelivr.net https://unpkg.com{script_extras}; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com; "
        "img-src 'self' data: blob: "
        "https://*.tile.openstreetmap.org https://tiles.stadiamaps.com "
        "https://server.arcgisonline.com https://unpkg.com; "
        "font-src 'self' data:; "
        f"connect-src 'self'{connect_extras}; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "object-src 'none'"
    )


CSP_POLICY = _build_csp_policy()

PERMISSIONS_POLICY = (
    "geolocation=(self), camera=(), microphone=(), payment=(), "
    "usb=(), magnetometer=(self), gyroscope=(self), accelerometer=(self)"
)


@app.after_request
def _record_user_agent_class(response):
    # Skip /metrics + /healthz so probes don't dominate the bucket counts.
    if request.path in ('/metrics', '/healthz'):
        return response
    requests_by_user_agent_class_total.labels(
        ua_class=classify_user_agent(request.headers.get('User-Agent'))
    ).inc()
    return response


@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = CSP_POLICY
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = PERMISSIONS_POLICY
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    return response

def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token

# Plausible Analytics — script + domain set via env. Both must be present
# to render the tracker; either missing → tracker silently disabled.
app.jinja_env.globals['plausible_script_url'] = os.getenv('PLAUSIBLE_SCRIPT_URL', '')
app.jinja_env.globals['plausible_domain'] = os.getenv('PLAUSIBLE_DOMAIN', '')

def validate_csrf():
    token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
    if not token or token != session.get('_csrf_token'):
        return False
    return True

SLOGANS = [
    ("On the Move?", "Navigate to the Nearest Base Stations for Uninterrupted Connectivity!"),
    ("Seeking Signal?", "Discover the Closest Connectivity Points for Seamless Communication!"),
    ("Chasing Coverage?", "Pinpoint the Best Signal Sources for Flawless Connections!"),
    ("Stay Connected Everywhere", "Discover the Closest Base Stations for Optimal Signal Strength!"),
    ("Dropping Calls?", "Catch the color for quality coverage!"),
    ("Found Getaway?", "Secure your signal!")
]

@app.route('/')
def home():
    slogan_title, slogan_text = random.choice(SLOGANS)
    return render_template('map.html', slogan_title=slogan_title, slogan_text=slogan_text)

def get_html_content_from_markdown(file_name):
    file_path = os.path.join(basedir, 'content', file_name)

    with open(file_path, 'r') as file:
        markdown_content = file.read()
    html_content = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])

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
@limiter.limit("30 per minute")
def submit_location():
    if not validate_csrf():
        csrf_failures_total.labels(endpoint='submit_location').inc()
        return jsonify({'error': 'Invalid request'}), 403
    try:
        data = request.get_json(silent=True) or {}
        if 'lat' not in data or 'lng' not in data:
            return jsonify({'error': 'Missing coordinates'}), 400
        user_lat = float(data['lat'])
        user_lng = float(data['lng'])

        if not (49.0 <= user_lat <= 55.5 and 14.0 <= user_lng <= 24.2):
            return jsonify({'error': 'Coordinates outside supported area'}), 400

        session['user_location'] = {'lat': user_lat, 'lng': user_lng}
        limit = data.get('limit', 9)
        max_distance = data.get('max_distance', None)

        station_search_total.labels(endpoint='submit_location').inc()
        nearest_stations = find_nearest_stations(user_lat, user_lng, limit=limit, max_distance=max_distance)

        if nearest_stations is None or not nearest_stations.get('stations'):
            empty_result_total.inc()
            return jsonify({'stations': [], 'count': 0})
        return jsonify(nearest_stations)

    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid coordinates'}), 400
    except Exception:
        app.logger.exception("Error in submit_location")
        return jsonify({'error': 'An error occurred'}), 500

@app.route('/stations', methods=['GET'])
@limiter.limit("30 per minute")
def get_stations():
    try:
        user_lat = request.args.get('lat')
        user_lng = request.args.get('lng')

        if user_lat and user_lng:
            user_lat = float(user_lat)
            user_lng = float(user_lng)
            if not (49.0 <= user_lat <= 55.5 and 14.0 <= user_lng <= 24.2):
                return jsonify({'error': 'Coordinates outside supported area'}), 400
        else:
            user_location = session.get('user_location')
            if user_location:
                user_lat = user_location['lat']
                user_lng = user_location['lng']
            else:
                return jsonify({"error": "User location not set"}), 400

        max_distance = request.args.get('max_distance', default=None, type=float)
        limit = request.args.get('limit', default=9, type=int)

        if max_distance is not None:
            if max_distance < 0.1 or max_distance > 10:
                return jsonify({"error": "Invalid parameter", "message": "Max distance must be between 0.1 and 10 km. Please respect it."}), 400
            # Set limit to None when a valid max_distance is provided to focus on distance-based filtering
            limit = None
        elif limit is not None:
            # Validate limit if max_distance is not provided
            if limit < 1 or limit > 10:
                return jsonify({"error": "Invalid parameter", "message": "Limit cannot exceed 10. Please respect it."}), 400

        frequency_bands = request.args.getlist('frequency_bands')
        raw_service_providers = request.args.getlist('service_provider')

        cleaned_service_providers = [provider.rstrip("'") for provider in raw_service_providers]

        # Track which providers / bands users actually filter on — answers
        # "what's worth highlighting in the UI" once we have promotion-driven
        # traffic. Bounded cardinality (≤4 providers, ≤14 bands).
        for provider in cleaned_service_providers:
            provider_filter_used_total.labels(provider=provider).inc()
        for band in frequency_bands:
            band_filter_used_total.labels(band=band).inc()

        station_search_total.labels(endpoint='stations').inc()
        result = find_nearest_stations(user_lat, user_lng, max_distance=max_distance, limit=limit, service_providers=cleaned_service_providers, frequency_bands=frequency_bands)
        stations = result.get("stations", [])
        stations_count = result.get("count", 0)
        if stations_count == 0:
            empty_result_total.inc()

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

    except (TypeError, ValueError):
        return jsonify({"error": "Invalid parameter values."}), 400
    except Exception:
        app.logger.exception("Error fetching stations")
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

@app.route('/search_stations', methods=['GET'])
@limiter.limit("30 per minute")
def search_stations():
    station_search_total.labels(endpoint='search_stations').inc()
    query = request.args.get('q', type=str, default='')
    limit = request.args.get('limit', type=int, default=5)

    if not query or len(query) < 2 or len(query) > 7:
        return jsonify({"stations": []})

    if not re.match("^[A-Za-z0-9]+$", query):
        return jsonify({"stations": []})

    # Search for stations with basestation_id starting with the query
    stations = BaseStation.query.filter(
        BaseStation.basestation_id.like(f'{query.upper()}%')
    ).limit(limit).all()

    stations_data = [{
        'basestation_id': s.basestation_id,
        'latitude': s.latitude,
        'longitude': s.longitude,
        'city': s.city,
        'service_provider': s.service_provider,
    } for s in stations]

    return jsonify({"stations": stations_data})

@app.route('/register', methods=['POST'])
@limiter.limit("5 per hour")
def register_user():
    if not validate_csrf():
        csrf_failures_total.labels(endpoint='register').inc()
        return jsonify({'error': 'Invalid request'}), 403

    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return "Invalid email address.", 400

    if not re.fullmatch(r"(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[^\w\s]).{8,64}$", password):
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
    except Exception:
        db.session.rollback()
        app.logger.exception("Error registering user")
        return jsonify({"success": False, "message": "Registration failed due to a server error."}), 500
    
@app.route('/login', methods=['POST'])
@limiter.limit("3 per minute")
def login_user():
    if not validate_csrf():
        csrf_failures_total.labels(endpoint='login').inc()
        return jsonify({'error': 'Invalid request'}), 403

    email = request.form.get('email')
    password = request.form.get('password')

    user = User.query.filter_by(email=email).first()

    if user and bcrypt.check_password_hash(user.password_hash, password):
        # Rotate the session to defend against fixation, but preserve the
        # CSRF token so the browser's <meta name="csrf-token"> remains valid
        # for the next POST (e.g. /logout). Otherwise every authenticated
        # POST after login would 403 until a full page reload.
        preserved_csrf = session.get('_csrf_token')
        session.clear()
        if preserved_csrf:
            session['_csrf_token'] = preserved_csrf
        else:
            preserved_csrf = generate_csrf_token()
        session['user_id'] = user.id
        return jsonify({
            "success": True,
            "message": "Logged in successfully.",
            "csrf_token": preserved_csrf,
        }), 200
    else:
        login_failures_total.inc()
        return jsonify({"success": False, "message": "Invalid email or password."}), 401

@app.route('/logout', methods=['POST'])
def logout():
    if not validate_csrf():
        csrf_failures_total.labels(endpoint='logout').inc()
        return jsonify({'error': 'Invalid request'}), 403
    session.pop('user_id', None)
    return jsonify({"success": True, "message": "You have been logged out."}), 200


@app.route('/session_check')
def session_check():
    is_logged_in = 'user_id' in session
    return jsonify({"logged_in": is_logged_in})


if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ['true', '1', 't']
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=debug_mode,
            host='0.0.0.0',
            port=port)
            #ssl_context=('/etc/ssl/localcerts/localhost+2.pem', '/etc/ssl/localcerts/localhost+2-key.pem'))
