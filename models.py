from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class BaseStation(db.Model):
    id = db.Column(db.Integer, primary_key=True)            # db index 
    basestation_id = db.Column(db.String, nullable=True)    # Real base station ID
    city = db.Column(db.String, nullable=True)              # City
    location = db.Column(db.String, nullable=True)          # Location/Street number
    service_provider = db.Column(db.String, nullable=True)  # ISP
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    frequency_band = db.Column(db.String, nullable=False)