from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class BaseStation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    IdStacji = db.Column(db.String, nullable=False)  # Real base station ID
    Miejscowość = db.Column(db.String, nullable=False)  # City
    Lokalizacja = db.Column(db.String, nullable=False)  # Street number
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    frequency_band = db.Column(db.String, nullable=False)
    # Add other fields as necessary, for example:
    # provider_name = db.Column(db.String, nullable=True)
    # signal_strength = db.Column(db.Float, nullable=True)