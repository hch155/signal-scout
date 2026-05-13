"""Public-API access control: Referer/Origin enforcement + API key tiers.

Threat model:
- Anyone can hit our public read endpoints (`/stations`, `/search_stations`,
  `/find_station`) and reconstruct the BTS dataset from a geographic grid.
  Rate limit alone (30/min/IP) doesn't stop a determined scraper with a
  handful of egress IPs.
- Honeypot rows let us *detect* leaks by salting the data with markers that,
  if ever seen in the wild, prove the source.

Defense layers (cheapest first):
1. **Referer / Origin check** — rejects naive `curl|python-requests` traffic
   that doesn't bother forging headers. Browser users unaffected because
   `fetch()` from the same origin sends Referer automatically.
2. **API key (`X-API-Key` header)** — bypasses the Referer check AND grants
   higher per-tier rate limits. Logged-in users get one auto-generated at
   registration, regenerable from /account.
3. **Honeypot detection** — known-fake basestation IDs increment a counter
   when looked up. Alertmanager fires on any hit.

What this module DOES NOT do:
- IP-based blocking (Cloud Run sees the LB IP, see `docs/ROADMAP.md`).
- CAPTCHAs / Cloudflare Turnstile (deferred — easier to bolt on once we
  have a frontend pattern for "human-check failed").
- Per-key billing or quotas beyond rate limit (commercial-tier work for
  later — `api_tier` column is the hook).
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from functools import wraps
from typing import Callable
from urllib.parse import urlparse

from flask import current_app, g, jsonify, request, session

from datetime import datetime

from database import db
from models import User, ApiKey
from observability import (
    api_referer_blocked_total,
    api_key_used_total,
    honeypot_hit_total,
    # PR #44: RED-method per-tier counters + funnel
    api_requests_total,
    api_request_duration_seconds,
    record_first_api_call,
)


logger = logging.getLogger(__name__)


# ── Tier configuration ─────────────────────────────────────────────────────

TIER_RATE_LIMITS = {
    # tier_name : (requests_per_minute, label_for_metrics)
    'anonymous': (10, 'anonymous'),     # browser traffic without an API key
    'free':      (60, 'free'),
    'pro':       (300, 'pro'),
    'enterprise': (3000, 'enterprise'),
}


def get_tier_limit(tier: str) -> str:
    """Flask-Limiter expects strings like '10 per minute'."""
    rpm, _label = TIER_RATE_LIMITS.get(tier, TIER_RATE_LIMITS['anonymous'])
    return f"{rpm} per minute"


# ── Honeypot ────────────────────────────────────────────────────────────────

def _load_honeypot_ids() -> set[str]:
    raw = os.getenv('HONEYPOT_BTS_IDS', '')
    return {x.strip().upper() for x in raw.split(',') if x.strip()}


# Loaded once per process. Hot path lookup (set membership = O(1)).
_HONEYPOT_IDS: set[str] = _load_honeypot_ids()


def is_honeypot(basestation_id: str) -> bool:
    return bool(basestation_id) and basestation_id.upper() in _HONEYPOT_IDS


def record_honeypot_hit(basestation_id: str, endpoint: str) -> None:
    """Bump the metric and warn-log. Caller still returns the same response
    shape they'd return for a normal miss — we don't want to tip off the
    scraper that they triggered a tripwire."""
    honeypot_hit_total.labels(endpoint=endpoint).inc()
    logger.warning(
        "Honeypot BTS hit: id=%s endpoint=%s referer=%s ua=%s",
        basestation_id,
        endpoint,
        (request.headers.get('Referer') or '')[:200],
        (request.headers.get('User-Agent') or '')[:200],
    )


# Audit fix L-NEW-4 (2026-04-27): planted-row marker. Honeypot rows
# in the BaseStation table carry this in `service_provider` so a
# manual DBA inspection can spot them (and so `seed_honeypot_rows`
# is idempotent across boots — we only insert when no marked row
# already exists for the ID). Capitalised so it sorts/displays in a
# way that doesn't mimic any real Polish operator.
HONEYPOT_PROVIDER_MARKER = '__HONEYPOT__'


def seed_honeypot_rows(app, db) -> int:
    """Idempotently insert a BaseStation row for each ID in
    HONEYPOT_BTS_IDS env. Returns count of newly-inserted rows.

    The original honeypot mechanism (env-list ID + lookup hit on
    /find_station and /search_stations exact-match) caught scrapers
    enumerating IDs directly but missed scrapers that prefix-searched
    /search_stations and only followed up on returned IDs — those
    never queried the honeypot directly because the honeypot rows
    weren't in the dataset. Planting them in the dataset closes the
    bypass: now /search_stations naturally surfaces the honeypot row
    as a candidate the scraper visits, triggering the env-list
    detection on the follow-up /find_station.

    Coordinates are random-but-stable per ID (hash-derived) inside
    Polish bounds so the row at least geographically belongs. The
    `service_provider` marker makes the rows trivial to recognise +
    keeps the helper idempotent.
    """
    import hashlib
    from models import BaseStation
    ids = _load_honeypot_ids()
    if not ids:
        return 0
    inserted = 0
    with app.app_context():
        # Polish-bounding-box constants (mirror find_nearest_stations).
        PL_LAT_MIN, PL_LAT_MAX = 49.0, 55.5
        PL_LNG_MIN, PL_LNG_MAX = 14.0, 24.2
        for bid in ids:
            existing = BaseStation.query.filter_by(
                basestation_id=bid,
                service_provider=HONEYPOT_PROVIDER_MARKER,
            ).first()
            if existing is not None:
                continue
            # Stable pseudo-random coords from sha1(id) so the same ID
            # always lands at the same spot across boots. usedforsecurity=False
            # — this is a deterministic ID-to-coord map, not a security primitive,
            # bandit B324 flags weak hashes regardless of intent.
            digest = hashlib.sha1(bid.encode('utf-8'), usedforsecurity=False).digest()
            lat_frac = int.from_bytes(digest[0:4], 'big') / 0xFFFFFFFF
            lng_frac = int.from_bytes(digest[4:8], 'big') / 0xFFFFFFFF
            lat = PL_LAT_MIN + lat_frac * (PL_LAT_MAX - PL_LAT_MIN)
            lng = PL_LNG_MIN + lng_frac * (PL_LNG_MAX - PL_LNG_MIN)
            row = BaseStation(
                basestation_id=bid,
                city='—',
                location='—',
                service_provider=HONEYPOT_PROVIDER_MARKER,
                latitude=lat,
                longitude=lng,
                frequency_band='LTE2100',
                rat='LTE',
                frequency_band_count=1,
                latitude_segment=int((lat - PL_LAT_MIN) * 10),
            )
            db.session.add(row)
            inserted += 1
        if inserted:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception("seed_honeypot_rows failed to commit")
                return 0
    return inserted


# ── Referer / Origin check ──────────────────────────────────────────────────

def _request_origin_host() -> str:
    """The Host header tells us what origin the browser thinks it talked to.
    Use that as the canonical 'allowed' origin so the check works regardless
    of whether we're on signal-scout.com, the Cloud Run URL, or a per-tenant
    subdomain in the future. Falls back to current_app config."""
    host = request.host
    return host.lower() if host else ''


def _matches_own_origin(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlparse(value)
        if not parsed.netloc:
            return False
        return parsed.netloc.lower() == _request_origin_host()
    except Exception:
        return False


def _has_valid_browser_origin() -> bool:
    """True if the request looks like it came from our own page in a browser.
    Browsers send Origin for cross-origin XHRs and Referer for top-level
    navs / same-origin XHRs alike. Modern fetch()-from-same-origin sends
    Referer reliably; we accept either header."""
    if _matches_own_origin(request.headers.get('Origin')):
        return True
    if _matches_own_origin(request.headers.get('Referer')):
        return True
    return False


# ── PR #47: Stripe-style hashed API keys ──────────────────────────────────
#
# Why sha256 (not bcrypt): API keys are 32-byte URL-safe random tokens
# (≈256 bits of entropy) — pre-image resistant by construction, no
# rainbow-table risk. bcrypt at 50-100 ms/verify is unworkable on the
# per-request hot path; sha256 at ~1 µs is the right tool. This matches
# the Stripe / GitHub / AWS playbook for high-entropy API tokens.

def hash_api_key(plaintext: str) -> str:
    """Return the hex sha256 digest of an API key.

    64-char lowercase hex output — fits the `key_hash VARCHAR(64)` column
    exactly. Empty/None input returns ''; callers should already have
    rejected empty tokens before lookup, but we don't want a `None.encode`
    crash on a malformed request.
    """
    if not plaintext:
        return ''
    return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()


def format_api_key_prefix(plaintext: str) -> str:
    """Return a display-only prefix in the form `first8…last4`.

    Stripe-ish: enough to recognise a key in a list ("which one is the iOS
    one?") without exposing enough entropy to brute-force. For
    `secrets.token_urlsafe(32)` (43 chars), 8+4=12 chars revealed leaves
    ≈31 chars (≈186 bits) of unrecoverable entropy.

    Edge cases: tokens shorter than 12 chars get a single `…` between as
    much head and tail as fits — protects test fixtures and any
    accidentally short legacy values without crashing the migration.
    """
    if not plaintext:
        return ''
    if len(plaintext) <= 12:
        # Degenerate path — show all but the middle char.
        head = plaintext[: len(plaintext) // 2]
        tail = plaintext[-(len(plaintext) - len(head) - 1):] if len(plaintext) > 1 else ''
        return f"{head}…{tail}"
    return f"{plaintext[:8]}…{plaintext[-4:]}"


# ── API key resolution ─────────────────────────────────────────────────────

def _resolve_api_key() -> User | None:
    """If a valid X-API-Key header is present, return the matching User.

    Resolution order (PR #14 multi-key + PR #47 hashed-at-rest):
    1. ApiKey table by `key_hash` — sha256(incoming) → single-row indexed
       lookup against the hashed column. Hot path; new keys live here.
       Bumps last_used_at on the ApiKey row so the /account UI can show
       freshness and the user can spot stale keys to revoke.
    2. ApiKey table by legacy plaintext `key` — back-compat for rows
       minted before PR #47 that haven't been backfilled yet (the boot
       migration covers them, but we keep the lookup for the rare
       race window — and for any pre-PR-#47 row whose plaintext is
       still in flight from a long-running client).
    3. User.api_key_hash — same hash lookup against the legacy
       single-key-per-user column.
    4. User.api_key — final legacy plaintext fallback.
    """
    raw = request.headers.get('X-API-Key', '').strip()
    if not raw or len(raw) > 128:
        return None

    raw_hash = hash_api_key(raw)

    # 1. New hashed lookup against ApiKey table (the hot path going forward).
    ak = ApiKey.query.filter_by(key_hash=raw_hash, revoked_at=None).first()
    # 2. Legacy plaintext fallback against ApiKey table.
    if ak is None:
        ak = ApiKey.query.filter_by(key=raw, revoked_at=None).first()
    if ak is not None:
        ak.last_used_at = datetime.utcnow()
        # PR #15: per-key call counter. Cheap inline UPDATE in the same txn
        # as last_used_at — gives /account an honest "calls" column.
        ak.total_calls = (ak.total_calls or 0) + 1
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return ak.user

    # 3 + 4. Fall back to legacy User.api_key — hashed first, plaintext last.
    u = User.query.filter_by(api_key_hash=raw_hash).first()
    if u is not None:
        return u
    return User.query.filter_by(api_key=raw).first()


# ── The decorator ──────────────────────────────────────────────────────────

def require_api_access(endpoint_label: str) -> Callable:
    """Apply to GET endpoints that return BTS data.

    Resolution order:
    1. Valid `X-API-Key` header → use that user's tier, skip Referer check.
    2. Logged-in session → 'free' tier (we know who it is).
    3. Same-origin Referer/Origin → 'anonymous' tier (browser visitors).
    4. Otherwise → 403 Forbidden.

    The chosen tier is stored on `flask.g.api_tier` for downstream code
    (e.g. tier-aware rate limiting in a future PR; right now we just label
    the metric).
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = _resolve_api_key()

            if user is not None:
                tier = user.api_tier or 'free'
                g.api_tier = tier
                g.api_key_user_id = user.id
                api_key_used_total.labels(tier=tier).inc()
                # PR #44 funnel step 4: first API call by this user.
                record_first_api_call(user.id)
            elif 'user_id' in session:
                # Authenticated browser session — treat as free tier.
                g.api_tier = 'free'
                api_key_used_total.labels(tier='session').inc()
                record_first_api_call(session.get('user_id'))
            elif _has_valid_browser_origin():
                g.api_tier = 'anonymous'
            else:
                api_referer_blocked_total.labels(endpoint=endpoint_label).inc()
                return jsonify({
                    "error": "access_denied",
                    "message": (
                        "This endpoint requires either an X-API-Key header or "
                        "a same-origin browser request. See /account to "
                        "generate an API key."
                    ),
                }), 403

            # PR #44: RED-method timing + outcome bucketing. Wraps the
            # handler so even an exception path counts toward the
            # error rate.
            with api_request_duration_seconds.labels(
                endpoint=endpoint_label
            ).time():
                try:
                    response = func(*args, **kwargs)
                except Exception:
                    api_requests_total.labels(
                        tier=g.get('api_tier', 'unknown'),
                        endpoint=endpoint_label,
                        outcome="server_error",
                    ).inc()
                    raise

            # Detect outcome from the response status code. Flask handlers
            # may return a Response, a (body, status[, headers]) tuple, or
            # a bare str; handle all three.
            status_code = 200
            outcome = "success"
            if isinstance(response, tuple):
                if len(response) >= 2 and isinstance(response[1], int):
                    status_code = response[1]
            else:
                status_code = getattr(response, 'status_code', 200)
            if 500 <= status_code < 600:
                outcome = "server_error"
            elif 400 <= status_code < 500:
                outcome = "client_error"
            api_requests_total.labels(
                tier=g.get('api_tier', 'unknown'),
                endpoint=endpoint_label,
                outcome=outcome,
            ).inc()
            return response

        return wrapper
    return decorator


# ── Schema migration helper (drops once we adopt Alembic in PR #1.5) ──────

def purge_submit_location_events_older_than_30_days(engine) -> int:
    """Delete SubmitLocationEvent rows older than 30 days. Returns the
    rowcount so a cron caller can log how many rows were swept.

    Idempotent. Safe to call from app boot AND from a Cloud Scheduler-
    triggered admin endpoint — that combination is the L-NEW-1 fix:
    boot covers the cold-instance case, scheduler covers the long-
    running min-instances=1 case where boot only fires every few
    weeks and the GDPR retention claim quietly lapses.
    """
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    if 'submit_location_event' not in insp.get_table_names():
        return 0
    with engine.begin() as conn:
        result = conn.execute(text(
            "DELETE FROM submit_location_event "
            "WHERE created_at < datetime('now', '-30 days')"
        ))
        return result.rowcount or 0


def ensure_user_api_columns(app, db) -> None:
    """Idempotently add api_key + api_tier columns to existing users.db.

    SQLAlchemy `db.create_all()` only adds new tables, never new columns to
    existing tables, so old prod databases won't pick up the new schema
    automatically. This helper does a focused ALTER TABLE on SQLite and
    backfills api_key for existing rows.

    Pulled out of app.py so the test harness can call it explicitly against
    its isolated test DB without booting the full app twice.
    """
    from sqlalchemy import inspect, text

    with app.app_context():
        engine = db.engines.get('users')
        if engine is None:
            return
        insp = inspect(engine)
        if 'user' not in insp.get_table_names():
            return  # create_all hasn't run yet — that path will create columns

        existing = {c['name'] for c in insp.get_columns('user')}
        with engine.begin() as conn:
            if 'api_key' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN api_key VARCHAR(64)"))
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_user_api_key ON user (api_key)"
                ))
            # PR #47: hashed API keys (Stripe-style). `api_key_hash` is the
            # sha256 hex digest used by the X-API-Key lookup hot path;
            # `api_key_prefix` is the `first8…last4` display label rendered
            # in /account so users can identify keys without us storing
            # plaintext. Indexed UNIQUE alongside the legacy `api_key`
            # index — both can coexist during the back-compat window.
            if 'api_key_hash' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN api_key_hash VARCHAR(64)"))
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_user_api_key_hash ON user (api_key_hash)"
                ))
            if 'api_key_prefix' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN api_key_prefix VARCHAR(40)"))
            if 'api_tier' not in existing:
                conn.execute(text(
                    "ALTER TABLE user ADD COLUMN api_tier VARCHAR(32) "
                    "DEFAULT 'free'"
                ))
            # PR #16: 2FA TOTP columns. SQLite does not allow non-constant
            # defaults in ALTER TABLE; for the boolean we coalesce in app
            # code (`user.totp_enabled or False`), so default-NULL is fine.
            if 'totp_secret' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN totp_secret VARCHAR(64)"))
            # PR #39: KMS-wrapped TOTP secret column. Stored base64-encoded
            # so SQLite TEXT works for binary KMS ciphertext.
            if 'totp_secret_enc' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN totp_secret_enc TEXT"))
            if 'totp_enabled' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN totp_enabled BOOLEAN DEFAULT 0"))
            if 'recovery_codes_json' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN recovery_codes_json TEXT"))
            # PR #19: company column for the simplified account UI.
            if 'company' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN company VARCHAR(120)"))
            # PR #26: account lockout columns.
            if 'failed_login_attempts' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0"))
            if 'locked_until' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN locked_until DATETIME"))
            # Audit fix M-NEW-3 (2026-04-27): TOTP replay defence.
            # Stamp the most-recently-used TOTP code so a re-presentation
            # within the validity window is rejected.
            if 'last_totp_code' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN last_totp_code VARCHAR(10)"))
            if 'last_totp_code_at' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN last_totp_code_at DATETIME"))
            # Audit fix M-NEW-7 (2026-04-27): audit_event hash chain.
            # Two new columns on a different table (audit_event), so we
            # probe its schema separately.
            audit_existing = {
                row[1] for row in conn.execute(text(
                    "PRAGMA table_info(audit_event)"
                ))
            }
            if audit_existing and 'prev_hash' not in audit_existing:
                conn.execute(text(
                    "ALTER TABLE audit_event ADD COLUMN prev_hash VARCHAR(64)"
                ))
            if audit_existing and 'row_hash' not in audit_existing:
                conn.execute(text(
                    "ALTER TABLE audit_event ADD COLUMN row_hash VARCHAR(64)"
                ))
            # PR #48.3: email_alerts_enabled (default True). Existing
            # rows get DEFAULT 1 → opt-in by default, matches pre-PR
            # behavior where every user was eligible to receive emails.
            # Flipping False is explicit (signed unsubscribe token or
            # /account preferences POST).
            if 'email_alerts_enabled' not in existing:
                conn.execute(text(
                    "ALTER TABLE user ADD COLUMN email_alerts_enabled "
                    "BOOLEAN NOT NULL DEFAULT 1"
                ))
            # PR #29: per-user station diff feed.
            if 'last_location_lat' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN last_location_lat FLOAT"))
            if 'last_location_lng' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN last_location_lng FLOAT"))
            # PR #36: drop legacy free-text profile columns + the
            # never-wired username + last_password_reset_request. The
            # /account UI was simplified to email + company in PR #19;
            # these columns have had zero callers since then. SQLite
            # 3.35+ supports ALTER TABLE … DROP COLUMN; the runtime
            # ships SQLite ≥3.40 (Python 3.12). Each DROP is wrapped
            # in an existence check so re-running this helper after the
            # columns are gone is a no-op.
            #
            # `username` carries a UNIQUE constraint (auto-index), and
            # SQLite refuses DROP COLUMN while a constraint references
            # the column. We strip the auto-index + the UNIQUE clause
            # from the table's CREATE statement first via the
            # writable_schema escape hatch, then DROP COLUMN works.
            _LEGACY_COLS = (
                'full_name', 'profile_picture', 'bio', 'date_of_birth',
                'username', 'last_password_reset_request',
            )
            if 'username' in existing:
                # Pull the current CREATE TABLE statement and strip the
                # `UNIQUE (username)` clause. Match both the SQLAlchemy
                # default formatting (",\n\tUNIQUE (username)") and a
                # bare ", UNIQUE (username)" so we tolerate hand-tweaked
                # schemas.
                import re as _re
                row = conn.execute(text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='user'"
                )).fetchone()
                if row is not None and row[0]:
                    cleaned = _re.sub(
                        r",\s*UNIQUE\s*\(\s*username\s*\)",
                        "",
                        row[0],
                    )
                    if cleaned != row[0]:
                        # Find the auto-index that backs the username
                        # UNIQUE constraint. pragma_index_info returns
                        # one row per indexed column; we want the auto-
                        # index whose only column is `username`.
                        username_autoidx = None
                        for (idx_name,) in conn.execute(text(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='index' AND tbl_name='user' "
                            "AND name LIKE 'sqlite_autoindex_user_%'"
                        )).fetchall():
                            cols = [
                                r[0] for r in conn.execute(
                                    text(
                                        "SELECT name FROM pragma_index_info(:n)"
                                    ),
                                    {"n": idx_name},
                                ).fetchall()
                            ]
                            if cols == ['username']:
                                username_autoidx = idx_name
                                break

                        conn.execute(text("PRAGMA writable_schema=ON"))
                        conn.execute(
                            text(
                                "UPDATE sqlite_master SET sql=:s "
                                "WHERE type='table' AND name='user'"
                            ),
                            {"s": cleaned},
                        )
                        if username_autoidx is not None:
                            conn.execute(
                                text(
                                    "DELETE FROM sqlite_master "
                                    "WHERE type='index' AND name=:n"
                                ),
                                {"n": username_autoidx},
                            )
                        conn.execute(text("PRAGMA writable_schema=OFF"))
            for _legacy in _LEGACY_COLS:
                if _legacy in existing:
                    conn.execute(text(f"ALTER TABLE user DROP COLUMN {_legacy}"))

        # Backfill api_key for any rows that lack one.
        users_without_key = User.query.filter(
            (User.api_key.is_(None)) | (User.api_key == '')
        ).all()
        for u in users_without_key:
            u.api_key = secrets.token_urlsafe(32)
            if not u.api_tier:
                u.api_tier = 'free'
        if users_without_key:
            db.session.commit()

        # PR #14: ensure the ApiKey table exists and migrate every existing
        # User.api_key into it as a row named "default". Idempotent — re-runs
        # find existing rows and skip.
        db.create_all(bind_key='users')  # creates ApiKey/AuditEvent if missing; noop otherwise

        # PR #20 hot-fix: db.create_all() does NOT add columns to existing
        # tables. ApiKey on prod was created in PR #14 *before* total_calls
        # existed, so we must ALTER it explicitly here. Without this, the
        # next deploy that reads ApiKey.total_calls (every X-API-Key
        # request) hits "no such column" and crashes container boot.
        if 'api_key' in insp.get_table_names():
            ak_cols = {c['name'] for c in insp.get_columns('api_key')}
            if 'total_calls' not in ak_cols:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE api_key ADD COLUMN total_calls INTEGER NOT NULL DEFAULT 0"
                    ))
            # PR #47: hashed API keys on the multi-key table. Same shape
            # as the User columns above — sha256 hex digest + display
            # prefix. The hash column is UNIQUE-indexed because the
            # X-API-Key middleware does a single-row lookup per request
            # (must be O(log n)).
            if 'key_hash' not in ak_cols:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE api_key ADD COLUMN key_hash VARCHAR(64)"
                    ))
                    conn.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "ix_api_key_key_hash ON api_key (key_hash)"
                    ))
            if 'key_prefix' not in ak_cols:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE api_key ADD COLUMN key_prefix VARCHAR(40)"
                    ))

        # PR #30: user_station_snapshot may have been created in PR #29
        # without the user_location_id column. db.create_all above
        # creates the new user_location table but, like above, won't
        # add columns to existing tables. ALTER explicitly so old prod
        # snapshots keep loading and new ones can stamp the FK.
        # Re-inspect after create_all so we see the freshly-created table.
        insp_post = inspect(engine)
        if 'user_station_snapshot' in insp_post.get_table_names():
            snap_cols = {c['name'] for c in insp_post.get_columns('user_station_snapshot')}
            if 'user_location_id' not in snap_cols:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE user_station_snapshot "
                        "ADD COLUMN user_location_id INTEGER"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_user_station_snapshot_user_location_id "
                        "ON user_station_snapshot (user_location_id)"
                    ))

        # PR #48.10: saved-location coverage alerts. last_coverage_state
        # holds the JSON snapshot of find_coverage_gaps() output captured
        # by scripts/coverage_alert_run.py after each monthly UKE refresh,
        # so the next run can diff. last_alert_sent_at lets the script
        # rate-limit (no double email if the script is run twice in the
        # same refresh window).
        if 'user_location' in insp_post.get_table_names():
            ul_cols = {c['name'] for c in insp_post.get_columns('user_location')}
            if 'last_coverage_state' not in ul_cols:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE user_location "
                        "ADD COLUMN last_coverage_state TEXT"
                    ))
            if 'last_alert_sent_at' not in ul_cols:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE user_location "
                        "ADD COLUMN last_alert_sent_at DATETIME"
                    ))

        # PR #48.4: 30-day retention on submit_location_event. Runs on
        # every boot so cron drift / forgotten retention jobs can't let
        # the table grow unbounded. Idempotent — older rows just don't
        # exist by the time the second deploy runs.
        # Audit fix L-NEW-1 (2026-04-27): also exposed as
        # purge_submit_location_events_older_than_30_days() so a
        # Cloud Scheduler job can hit /admin/run_retention and trigger
        # the same DELETE on a fixed cadence. Boot-only retention
        # silently lapsed when min-instances=1 kept a worker hot for
        # weeks; the explicit cron path closes that GDPR gap.
        purge_submit_location_events_older_than_30_days(engine)

        for u in User.query.filter(User.api_key.isnot(None)).all():
            already = ApiKey.query.filter_by(user_id=u.id, key=u.api_key).first()
            if already is None:
                db.session.add(ApiKey(
                    user_id=u.id,
                    name='default',
                    key=u.api_key,
                    created_at=u.registration_date or datetime.utcnow(),
                ))
        db.session.commit()

        # PR #47: idempotent backfill of `key_hash` + `key_prefix` for any
        # row that still has a plaintext value but no hash yet. After this
        # boot pass every existing key resolves through the hashed hot
        # path; only post-cutover-minted keys (hash-only) need to be
        # written by route handlers from now on. Re-runs are no-ops
        # because the WHERE clause filters on `key_hash IS NULL`.
        users_to_backfill = User.query.filter(
            User.api_key.isnot(None),
            User.api_key_hash.is_(None),
        ).all()
        for u in users_to_backfill:
            u.api_key_hash = hash_api_key(u.api_key)
            u.api_key_prefix = format_api_key_prefix(u.api_key)
        keys_to_backfill = ApiKey.query.filter(
            ApiKey.key.isnot(None),
            ApiKey.key_hash.is_(None),
        ).all()
        for k in keys_to_backfill:
            k.key_hash = hash_api_key(k.key)
            k.key_prefix = format_api_key_prefix(k.key)
        if users_to_backfill or keys_to_backfill:
            db.session.commit()


def generate_api_key() -> str:
    """Used by the registration flow + /account regenerate."""
    return secrets.token_urlsafe(32)
