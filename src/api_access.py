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


# ── API key resolution ─────────────────────────────────────────────────────

def _resolve_api_key() -> User | None:
    """If a valid X-API-Key header is present, return the matching User.

    Resolution order (PR #14 multi-key):
    1. ApiKey table — active (not revoked) keys, user → tier from User.api_tier.
       Bumps last_used_at on the ApiKey row so the /account UI can show
       freshness and the user can spot stale keys to revoke.
    2. Legacy User.api_key column — kept during the migration window so any
       in-flight clients using the original key keep working.
    """
    raw = request.headers.get('X-API-Key', '').strip()
    if not raw or len(raw) > 128:
        return None
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
            elif 'user_id' in session:
                # Authenticated browser session — treat as free tier.
                g.api_tier = 'free'
                api_key_used_total.labels(tier='session').inc()
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

            return func(*args, **kwargs)

        return wrapper
    return decorator


# ── Schema migration helper (drops once we adopt Alembic in PR #1.5) ──────

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
            if 'totp_enabled' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN totp_enabled BOOLEAN DEFAULT 0"))
            if 'recovery_codes_json' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN recovery_codes_json TEXT"))
            # PR #19: company column for the simplified account UI.
            if 'company' not in existing:
                conn.execute(text("ALTER TABLE user ADD COLUMN company VARCHAR(120)"))

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


def generate_api_key() -> str:
    """Used by the registration flow + /account regenerate."""
    return secrets.token_urlsafe(32)
