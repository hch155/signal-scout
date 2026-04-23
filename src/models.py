from datetime import datetime, timedelta
from database import db
from werkzeug.security import generate_password_hash, check_password_hash
import os

class BaseStation(db.Model):
    __tablename__ = 'base_station'
    __table_args__ = (
        db.Index('ix_segment_provider_band', 'latitude_segment', 'service_provider', 'frequency_band'),
    )
    id = db.Column(db.Integer, primary_key=True)
    basestation_id = db.Column(db.String, nullable=True)
    city = db.Column(db.String, nullable=True)
    location = db.Column(db.String, nullable=True)
    service_provider = db.Column(db.String, nullable=True)
    latitude = db.Column(db.Float, index=True, nullable=False)
    longitude = db.Column(db.Float, index=True, nullable=False)
    frequency_band = db.Column(db.String, index=True, nullable=False)
    rat = db.Column(db.String, nullable=True)
    frequency_band_count = db.Column(db.Integer, default=-1, nullable=True)
    latitude_segment = db.Column(db.Integer, index=True, default=-1, nullable=True)

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
    # PR #5: API access. Indexed for the X-API-Key header lookup hot path.
    # api_tier values: 'free' (default), 'pro', 'enterprise' — the latter
    # two unlock higher per-tier rate limits and bypass the Referer check.
    api_key = db.Column(db.String(64), unique=True, index=True)
    api_tier = db.Column(db.String(32), default='free')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ApiKey(db.Model):
    """PR #14: named API keys. Multiple per user, individually revokable.

    The legacy User.api_key column is kept as the "default" key for
    backward compat — every newly issued ApiKey row is also reflected
    there for the duration of the migration window so old code paths
    that read User.api_key keep working. Plan to drop the column once
    the cutover is verified in prod (separate PR).
    """
    __bind_key__ = 'users'
    __tablename__ = 'api_key'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'),
                        nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    # Indexed because the X-API-Key middleware does a single-row lookup
    # per request — must be O(log n).
    key = db.Column(db.String(64), unique=True, index=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime)
    # Soft-delete: revoked keys can't authenticate but are kept around so the
    # user can see what was active when (audit trail, rotation history).
    revoked_at = db.Column(db.DateTime)

    user = db.relationship('User', backref=db.backref('api_keys', lazy='dynamic'))

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None