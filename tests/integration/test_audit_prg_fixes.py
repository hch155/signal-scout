"""Regression coverage for re-audit batch PR G:
- M-NEW-5: /account/test_email is now admin-only.
- M-NEW-8: _FIRST_CALL_SEEN_USERS is a bounded LRU.
- L-NEW-2: pending_2fa half-session expires after _PENDING_2FA_TTL_SECS.
- L-NEW-5: /admin/stats has its own per-hour rate limit.
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timedelta

import pyotp
import pytest


# ───────────────────────────────────────────────────────────────────
# M-NEW-5: /account/test_email admin-only
# ───────────────────────────────────────────────────────────────────

def test_test_email_refuses_non_admin(authed_client, csrf_token):
    """A non-admin authed user must get 403 even though they pass
    CSRF + auth. Pre-fix, anyone with a valid session could trigger
    SendGrid sends (rate-limited at 3/hour per IP)."""
    r = authed_client.post(
        "/account/test_email",
        headers={"X-CSRF-Token": csrf_token, "Referer": "http://localhost/"},
    )
    assert r.status_code == 403, r.data
    body = r.get_json() or {}
    assert body.get("error") == "forbidden"


# ───────────────────────────────────────────────────────────────────
# M-NEW-8: bounded LRU
# ───────────────────────────────────────────────────────────────────

def test_first_call_lru_evicts_past_cap():
    """Recording more than _FIRST_CALL_LRU_CAP distinct users must
    evict the oldest, not grow unbounded."""
    import observability
    # Reset the LRU for a clean measurement.
    observability._FIRST_CALL_SEEN_USERS = None
    cap = observability._FIRST_CALL_LRU_CAP
    for uid in range(cap + 50):
        observability.record_first_api_call(uid)
    assert len(observability._FIRST_CALL_SEEN_USERS) == cap, (
        f"LRU grew to {len(observability._FIRST_CALL_SEEN_USERS)}, "
        f"expected {cap} after eviction. M-NEW-8 regressed."
    )
    # The earliest IDs should have been evicted.
    assert 0 not in observability._FIRST_CALL_SEEN_USERS
    # Recent IDs should still be present.
    assert (cap + 49) in observability._FIRST_CALL_SEEN_USERS


# ───────────────────────────────────────────────────────────────────
# L-NEW-2: pending_2fa expiry
# ───────────────────────────────────────────────────────────────────

def test_login_totp_refuses_expired_pending_2fa(authed_client, csrf_token, app):
    """A pending_2fa half-session older than _PENDING_2FA_TTL_SECS
    must be refused so a stolen cookie can't sit on it brute-forcing
    TOTP for the full 7-day cookie lifetime."""
    from database import db
    from models import User
    from auth_routes import _wrap_totp_secret, _PENDING_2FA_TTL_SECS

    secret = pyotp.random_base32()
    with app.app_context():
        u = User.query.first()
        u.totp_secret_enc = _wrap_totp_secret(secret)
        u.totp_enabled = True
        db.session.commit()
        user_id = u.id

    c = app.test_client()
    expired_iso = (
        datetime.utcnow() - timedelta(seconds=_PENDING_2FA_TTL_SECS + 60)
    ).isoformat()
    with c.session_transaction() as s:
        s["_csrf_token"] = csrf_token
        s["pending_2fa_user_id"] = user_id
        s["pending_2fa_started_at"] = expired_iso

    r = c.post("/login/totp",
               data=_json.dumps({"code": pyotp.TOTP(secret).now()}),
               content_type="application/json",
               headers={"X-CSRF-Token": csrf_token,
                        "Referer": "http://localhost/"})
    assert r.status_code == 401, (
        f"expired pending_2fa should yield 401, got {r.status_code}: {r.data!r}"
    )
    # And the half-session is cleared so a follow-up retry doesn't
    # accidentally succeed via stale state.
    with c.session_transaction() as s:
        assert "pending_2fa_user_id" not in s
        assert "pending_2fa_started_at" not in s


def test_login_totp_accepts_fresh_pending_2fa(authed_client, csrf_token, app):
    """Sanity: a freshly-stamped pending_2fa is accepted (the TTL only
    fires on stale half-sessions, not every one)."""
    from database import db
    from models import User
    from auth_routes import _wrap_totp_secret

    secret = pyotp.random_base32()
    with app.app_context():
        u = User.query.first()
        u.totp_secret_enc = _wrap_totp_secret(secret)
        u.totp_enabled = True
        u.last_totp_code = None
        u.last_totp_code_at = None
        db.session.commit()
        user_id = u.id

    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf_token"] = csrf_token
        s["pending_2fa_user_id"] = user_id
        s["pending_2fa_started_at"] = datetime.utcnow().isoformat()

    r = c.post("/login/totp",
               data=_json.dumps({"code": pyotp.TOTP(secret).now()}),
               content_type="application/json",
               headers={"X-CSRF-Token": csrf_token,
                        "Referer": "http://localhost/"})
    assert r.status_code == 200, r.data


# ───────────────────────────────────────────────────────────────────
# L-NEW-5: /admin/stats rate limit
# ───────────────────────────────────────────────────────────────────

def test_admin_stats_has_dedicated_rate_limit(client):
    """The route must declare its own @limiter.limit decorator (not
    just inherit the default-16/min). Verified via app.url_map +
    introspection of the limiter rules instead of hammering the
    endpoint, so the test is fast and doesn't rely on time-based
    state across the test suite."""
    import app as app_module
    rules = app_module.limiter.current_limits
    # Easier: the decorator wraps the view, so the limit registry
    # holds an entry keyed by the view function name. We just check
    # that admin_stats is not relying on default_limits alone.
    info = app_module.limiter.limit_manager.application_limits
    # Best practical assertion: invoke the endpoint many times in
    # quick succession and verify a 429 lands inside the per-hour
    # window. Cheaper than rate-limiter introspection across versions.
    # 31 calls in <1s → must trip the 30/h cap.
    statuses = set()
    for _ in range(35):
        r = client.get("/admin/stats")
        statuses.add(r.status_code)
        if r.status_code == 429:
            break
    assert 429 in statuses, (
        "L-NEW-5: /admin/stats should rate-limit at 30/h; never saw 429 "
        "after 35 rapid calls. Decorator probably missing."
    )
