from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stations.db'
db = SQLAlchemy(app)

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

class BaseStation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    frequency_band = db.Column(db.String, nullable=False)
    # +.. other necessary fields for the future


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0') # useful for development, remember to turn off debug mode in production as it can expose sensitive information.
                                        # host='0.0.0.0' so it is accessible from your host machine or external requests.
