from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

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
    rat = db.Column(db.String, nullable=True)

class User(db.Model):
    __bind_key__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)