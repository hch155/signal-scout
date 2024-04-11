from datetime import datetime, timedelta
from database import db
from werkzeug.security import generate_password_hash, check_password_hash
import os

class BaseStation(db.Model):
    __tablename__ = 'base_station'
    id = db.Column(db.Integer, primary_key=True)
    basestation_id = db.Column(db.String, nullable=True)
    city = db.Column(db.String, nullable=True)
    location = db.Column(db.String, nullable=True)
    service_provider = db.Column(db.String, nullable=True)
    latitude = db.Column(db.Float, index=True, nullable=False)
    longitude = db.Column(db.Float, index=True, nullable=False)
    frequency_band = db.Column(db.String, nullable=False)
    rat = db.Column(db.String, nullable=True)
    frequency_band_count = db.Column(db.Integer, default=-1, nullable=True)
    latitude_segment = db.Column(db.Integer, default=-1, nullable=True)

class User(db.Model):
    __bind_key__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    username = db.Column(db.String(80), unique=True)
    full_name = db.Column(db.String(100))
    profile_picture = db.Column(db.String(255))
    bio = db.Column(db.Text)
    date_of_birth = db.Column(db.Date)
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_date = db.Column(db.DateTime)
    role = db.Column(db.String(80), default='user')
    status = db.Column(db.String(80), default='active')
    last_password_change = db.Column(db.DateTime, default=datetime.utcnow)
    last_password_reset_request = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)