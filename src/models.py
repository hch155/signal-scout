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
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_date = db.Column(db.DateTime)
    role = db.Column(db.String(80), default='user')
    status = db.Column(db.String(80), default='active')
    last_password_change = db.Column(db.DateTime, default=datetime.utcnow)
    # PR #5: API access. Indexed for the X-API-Key header lookup hot path.
    # api_tier values: 'free' (default), 'pro', 'enterprise' — the latter
    # two unlock higher per-tier rate limits and bypass the Referer check.
    api_key = db.Column(db.String(64), unique=True, index=True)
    api_tier = db.Column(db.String(32), default='free')
    # PR #16: 2FA TOTP. totp_secret is the raw base32 secret (matches what
    # pyotp emits); kept in plaintext for now, following the same trade-off
    # as User.api_key. Encrypting at rest is a follow-up once we introduce
    # a KMS key. totp_enabled gates the login flow: only True after the
    # user has successfully verified a code during setup. recovery_codes is
    # a JSON array of bcrypt hashes (one per single-use recovery code).
    totp_secret = db.Column(db.String(64))
    totp_enabled = db.Column(db.Boolean, default=False, nullable=False)
    recovery_codes_json = db.Column(db.Text)
    # PR #19: company name. The simplified /account UI asks only for
    # company; the legacy free-text profile columns (full_name, bio,
    # profile_picture, date_of_birth) plus username and the never-wired
    # last_password_reset_request were dropped in PR #36.
    company = db.Column(db.String(120))
    # PR #29: per-user station diff feed.
    # last_location_* is the centre of the snapshot radius. Persisted by
    # /submit_location whenever a logged-in user clicks the map. Anonymous
    # users + users who never clicked have NULL → no snapshots.
    last_location_lat = db.Column(db.Float)
    last_location_lng = db.Column(db.Float)
    # PR #26: account lockout. Counter bumped on each failed /login;
    # reset on success. Once it hits LOCKOUT_THRESHOLD, locked_until is
    # stamped with now + LOCKOUT_DURATION; subsequent login attempts are
    # refused with 403 until the timestamp passes. Two columns rather than
    # one packed value so an ops-side manual reset only needs to clear
    # locked_until without losing audit context.
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)

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
    # PR #15: per-key call counter. Bumped in api_access middleware alongside
    # last_used_at on every authenticated API hit (single-row UPDATE in the
    # same txn — cheap on SQLite).
    total_calls = db.Column(db.Integer, default=0, nullable=False)
    # Soft-delete: revoked keys can't authenticate but are kept around so the
    # user can see what was active when (audit trail, rotation history).
    revoked_at = db.Column(db.DateTime)

    user = db.relationship('User', backref=db.backref('api_keys', lazy='dynamic'))

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class AuditEvent(db.Model):
    """PR #15: per-user audit trail of security-sensitive actions.

    Written by the auth_routes hooks for login/logout/password/profile/
    delete/api-key flows. Surfaced in the /account "Recent activity" card
    so users can spot suspicious activity (e.g. login from an IP they
    don't recognize) and rotate credentials if needed.

    FK has ON DELETE CASCADE so /account/delete also wipes the audit
    history — keeps GDPR right-to-erasure clean.
    """
    __bind_key__ = 'users'
    __tablename__ = 'audit_event'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,
                        db.ForeignKey('user.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    event_type = db.Column(db.String(40), nullable=False, index=True)
    # Snapshot of request metadata at the moment of the event. Truncated
    # generously so a malicious UA header can't bloat a row.
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(256))
    # JSON-encoded extra context (e.g. login.fail → {"reason":"bad_password"};
    # apikey.created → {"name":"iOS app","key_id":42}).
    meta_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)

    user = db.relationship('User',
                           backref=db.backref('audit_events',
                                              cascade='all, delete-orphan',
                                              lazy='dynamic'))


class UserLocation(db.Model):
    """PR #30: multiple named saved locations per user.

    The PR #29 single-location model (`User.last_location_*`) is kept for
    back-compat — snapshots taken before this PR landed still carry only
    `user_id`. New snapshots also stamp `user_location_id` so the per-
    location /account/locations/<id>/changes view can scope its diff
    correctly.

    `radius_km` defaults to 15 km (matches PR #29 SNAPSHOT_RADIUS_KM —
    bigger than the original 5 km so rural users in low-density areas
    still see meaningful samples).

    `alerting_enabled` is the toggle the user mentioned in the ask:
    when False, the (future) email digest job will skip this location.
    Snapshot capture is unaffected — taking a snapshot from /account is
    always allowed regardless of the toggle, since "show me right now"
    is independent from "email me when something changes".

    FK ON DELETE CASCADE so /account/delete wipes saved locations (GDPR
    right-to-erasure) and so deleting a location wipes its snapshots.
    """
    __bind_key__ = 'users'
    __tablename__ = 'user_location'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,
                        db.ForeignKey('user.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(255))
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    radius_km = db.Column(db.Float, default=15.0, nullable=False)
    alerting_enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User',
                           backref=db.backref('saved_locations',
                                              cascade='all, delete-orphan',
                                              lazy='dynamic'))


class UserStationSnapshot(db.Model):
    """PR #29: per-user station snapshot. Captures the list of BTS within
    `radius_km` of the user's saved location at `taken_at`. Diffs are
    computed on the fly when /account/changes renders, comparing
    consecutive snapshots — no separate diff table.

    JSON payload format: list of {basestation_id, service_provider,
    location, latitude, longitude, frequency_bands: [...], distance}.

    PR #30: `user_location_id` (nullable) scopes a snapshot to one of the
    user's named saved locations (UserLocation rows). Pre-PR-#30
    snapshots have it NULL — they belong to the user's legacy
    `User.last_location_*` and are still rendered by /account/changes.

    FK ON DELETE CASCADE so /account/delete wipes the trail (GDPR), and
    so deleting a UserLocation cascades to its snapshots.
    """
    __bind_key__ = 'users'
    __tablename__ = 'user_station_snapshot'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,
                        db.ForeignKey('user.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    user_location_id = db.Column(db.Integer,
                                 db.ForeignKey('user_location.id',
                                               ondelete='CASCADE'),
                                 nullable=True, index=True)
    taken_at = db.Column(db.DateTime, default=datetime.utcnow,
                         nullable=False, index=True)
    # Centre of the snapshot — copied from User.last_location_* (or the
    # parent UserLocation) at the moment the snapshot was taken so we can
    # render diffs even after the user moves the saved location.
    centre_lat = db.Column(db.Float, nullable=False)
    centre_lng = db.Column(db.Float, nullable=False)
    radius_km = db.Column(db.Float, default=5.0, nullable=False)
    stations_json = db.Column(db.Text, nullable=False)

    user = db.relationship('User',
                           backref=db.backref('station_snapshots',
                                              cascade='all, delete-orphan',
                                              lazy='dynamic'))
    location = db.relationship('UserLocation',
                               backref=db.backref('snapshots',
                                                  cascade='all, delete-orphan',
                                                  lazy='dynamic'))