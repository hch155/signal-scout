from datetime import datetime
from database import db
from werkzeug.security import generate_password_hash, check_password_hash

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
    #
    # PR #47 (hashed API keys, Stripe-style): `api_key` is the legacy
    # plaintext column kept ONLY for the back-compat lookup window — new
    # rows leave it NULL. The hot-path lookup hashes incoming X-API-Key
    # values and matches against `api_key_hash` (sha256 hex digest).
    # `api_key_prefix` is `first8…last4` of the original token, surfaced
    # in /account so the user can recognise which key they're holding
    # without our DB ever storing the secret. Plan: drop `api_key` in a
    # follow-up PR once this hash column has covered all in-flight callers.
    api_key = db.Column(db.String(64), unique=True, index=True)
    api_key_hash = db.Column(db.String(64), unique=True, index=True)
    api_key_prefix = db.Column(db.String(40))
    api_tier = db.Column(db.String(32), default='free')
    # PR #16: 2FA TOTP. totp_secret is the raw base32 secret (matches what
    # pyotp emits); kept in plaintext for now, following the same trade-off
    # as User.api_key. Encrypting at rest is a follow-up once we introduce
    # a KMS key. totp_enabled gates the login flow: only True after the
    # user has successfully verified a code during setup. recovery_codes is
    # a JSON array of bcrypt hashes (one per single-use recovery code).
    totp_secret = db.Column(db.String(64))
    # PR #39: KMS-wrapped totp_secret. Populated when GCP_KMS_KEY_NAME is set
    # (NoopKms otherwise — passthrough, written as-is). Read path prefers
    # this column; falls back to plaintext `totp_secret` for rows minted
    # before activation. Stored as base64 text so SQLite TEXT column works
    # — KMS ciphertext is binary.
    totp_secret_enc = db.Column(db.Text)
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
    # Audit fix M-NEW-3 (2026-04-27): TOTP replay defence. Each
    # successful TOTP code is stamped here; a re-presentation of the
    # SAME code within the validity window (~90 s with valid_window=1)
    # is refused. Closes the "shoulder-surf one TOTP, fire it twice"
    # vector. Stored as the raw 6-digit string + UTC timestamp; small
    # enough that the index isn't worth it.
    last_totp_code = db.Column(db.String(10))
    last_totp_code_at = db.Column(db.DateTime)
    # PR #48.3: master toggle for transactional email delivery. Default
    # True. Flipped to False either by clicking the unsubscribe link in
    # an email footer (signed token → /unsubscribe/<token>) or via the
    # /account preferences UI. emails._send() short-circuits when this
    # is False — no email of any kind goes out (including security
    # alerts). Trade-off documented in /privacy + the unsubscribe
    # confirmation page.
    email_alerts_enabled = db.Column(db.Boolean, default=True, nullable=False)
    # 2026-06-11: email verification. NULL = unverified (post-migration
    # signups only — migration 0002 backfills legacy rows with their
    # registration_date, since blocking long-standing accounts
    # retroactively would be wrong). Stamped by /verify-email or
    # immediately on OAuth signup (provider already verified the email).
    # Coverage-alert sends are gated on this so an attacker can't
    # register someone else's address and aim alert mail at it.
    email_verified_at = db.Column(db.DateTime)

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None

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

    PR #47 (Stripe-style hashed keys): plaintext `key` is now nullable
    and only present on rows minted before this PR; new rows store only
    `key_hash` (sha256) + `key_prefix` (`first8…last4` for display).
    """
    __bind_key__ = 'users'
    __tablename__ = 'api_key'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'),
                        nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    # Indexed because the X-API-Key middleware does a single-row lookup
    # per request — must be O(log n).
    #
    # PR #47 (hashed API keys, Stripe-style): `key` is now nullable and
    # only populated for legacy rows minted before this PR. The lookup
    # hot path matches `key_hash` (sha256 hex digest of the original
    # token); `key_prefix` (`first8…last4`) is rendered in /account so
    # users can identify which key they're holding without us ever
    # storing the plaintext. New rows: key=NULL, key_hash + key_prefix
    # populated. Backfill on boot copies hash + prefix for any legacy
    # row with a non-null `key`. Drop `key` column in a follow-up PR
    # once we've verified no in-flight callers depend on it.
    key = db.Column(db.String(64), unique=True, index=True, nullable=True)
    key_hash = db.Column(db.String(64), unique=True, index=True, nullable=True)
    key_prefix = db.Column(db.String(40), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime)
    # PR #15: per-key call counter. Bumped in api_access middleware alongside
    # last_used_at on every authenticated API hit (single-row UPDATE in the
    # same txn — cheap on SQLite).
    total_calls = db.Column(db.Integer, default=0, nullable=False)
    # Soft-delete: revoked keys can't authenticate but are kept around so the
    # user can see what was active when (audit trail, rotation history).
    revoked_at = db.Column(db.DateTime)

    # NOTE: lazy='dynamic' makes SQLAlchemy cascade='all, delete-orphan' a
    # silent no-op on this relationship, so account deletion cleans up
    # ApiKey rows EXPLICITLY in auth_routes.delete_account. If you ever
    # switch this to lazy='select', remove that explicit step.
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
    # Audit fix M-NEW-7 (2026-04-27): tamper-evident chain. Each
    # row's `row_hash` includes the previous event's row_hash for the
    # same user, so an attacker who deletes / modifies a row
    # invalidates the chain at every subsequent row. Verification is
    # the verify_audit_chain_for_user() helper in auth_routes.
    # Per-user (not global) chain so /account/delete cascade still
    # cleanly drops the trail.
    prev_hash = db.Column(db.String(64))
    row_hash = db.Column(db.String(64))

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
    # PR #48.10: snapshot of last find_coverage_gaps() output for this
    # spot — JSON-encoded, written by scripts/coverage_alert_run.py
    # after each monthly UKE refresh. NULL means "first run, nothing
    # to compare against yet". The send-loop compares this to the
    # freshly-computed result and emails only when meaningful diff
    # (gained/lost a band, or nearest-BTS distance change > 1 km).
    last_coverage_state = db.Column(db.Text, nullable=True)
    last_alert_sent_at = db.Column(db.DateTime, nullable=True)
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


class SubmitLocationEvent(db.Model):
    """PR #48.4: pseudonymized usage event. Written best-effort on every
    successful /submit_location call so /admin/stats can answer "where /
    when / what browser are people using the app from".

    GDPR posture (Art. 6(1)(f) — legitimate interest):
    - No raw IP, no precise coords, no full User-Agent string.
    - `session_hash` is sha256(session_cookie) — pseudonym, not
      reversible to a person.
    - `lat_bucket` / `lng_bucket` are rounded to 2 decimal places
      (~1km grid) so we can spot dense regions without geolocating
      individuals.
    - `browser_class` is the bucketed UA category from observability.
    - 30-day retention enforced on app boot via DELETE FROM ...
      WHERE created_at < datetime('now', '-30 days').

    Disclosed in /privacy. Cascade ON DELETE for the rare case the
    user_id reference is set (logged-in users opted in to having their
    actions linkable for their own /account view; right-to-erasure
    wipes those rows when the user deletes their account)."""
    __bind_key__ = 'users'
    __tablename__ = 'submit_location_event'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    session_hash = db.Column(db.String(64), index=True)
    user_id = db.Column(db.Integer,
                        db.ForeignKey('user.id', ondelete='CASCADE'),
                        nullable=True, index=True)
    lat_bucket = db.Column(db.Float, nullable=False)
    lng_bucket = db.Column(db.Float, nullable=False)
    in_pl = db.Column(db.Boolean, default=False, nullable=False)
    browser_class = db.Column(db.String(32))
    api_tier = db.Column(db.String(32))

    user = db.relationship('User',
                           backref=db.backref('submit_events',
                                              cascade='all, delete-orphan',
                                              lazy='dynamic'))

class StatsSnapshot(db.Model):
    """Monthly /stats aggregate snapshot. Replaces stats_history.jsonl.

    One row per UKE refresh. `snapshot_key` is the data date (YYYY-MM-DD),
    UNIQUE so re-recording the same refresh is idempotent and ascending
    string sort == chronological order. `payload` is the JSON-encoded
    aggregate (physical_sites, sites_per_generation, provider_totals,
    generation_breakdown, generation_totals, grand_total_sites,
    grand_total_entries). `recorded_at` is the ISO time we observed it.
    """
    __bind_key__ = 'users'
    __tablename__ = 'stats_snapshot'

    id = db.Column(db.Integer, primary_key=True)
    snapshot_key = db.Column(db.Text, unique=True, nullable=False)
    recorded_at = db.Column(db.Text)
    payload = db.Column(db.Text, nullable=False)


class EmailEvent(db.Model):
    """2026-04-29: SendGrid Event Webhook ingestion. One row per
    delivery / open / click / bounce / spamreport / dropped /
    unsubscribe event SendGrid posts to /webhooks/sendgrid.

    Why store: without this we have no idea which alerts bounced,
    which got opened, who marked us as spam — i.e. no deliverability
    visibility. Bulk-sender rules require we react to spam reports
    promptly; we can't react to what we don't see.

    `sg_event_id` is the dedupe key — SendGrid retries with the same
    id, so a UNIQUE constraint makes the webhook idempotent. `raw_json`
    keeps the full event for forensic queries (custom args, trace_id
    etc.) without bloating the indexed columns.
    """
    __bind_key__ = 'users'
    __tablename__ = 'email_event'

    id = db.Column(db.Integer, primary_key=True)
    sg_event_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    sg_message_id = db.Column(db.String(128), index=True)
    email = db.Column(db.String(254), nullable=False, index=True)
    event_type = db.Column(db.String(32), nullable=False, index=True)
    sg_timestamp = db.Column(db.DateTime, nullable=True, index=True)
    reason = db.Column(db.String(255), nullable=True)
    raw_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)


class EmailSuppression(db.Model):
    """2026-04-29: addresses we must not send to. Mirror of SendGrid's
    server-side list, populated by the event webhook on hard-bounce
    / spamreport / dropped events. Looked up in emails._send before
    any backend call — cheaper than paying SendGrid to reject and
    keeps us off Gmail's bulk-sender naughty-list.

    `email` is lower-cased on insert (canonical form). `reason` is
    SendGrid's event_type ('bounce', 'spamreport', 'dropped',
    'group_unsubscribe', 'unsubscribe'). `details` keeps SendGrid's
    free-text reason (e.g. 'mailbox does not exist') for debugging.
    """
    __bind_key__ = 'users'
    __tablename__ = 'email_suppression'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    reason = db.Column(db.String(64), nullable=False)
    details = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)
