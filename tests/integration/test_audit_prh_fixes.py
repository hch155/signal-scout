"""Regression coverage for re-audit batch PR H:
- M-NEW-1 (partial): SQLite busy-timeout 30s on both binds.
- L-NEW-1: retention DELETE extracted as a callable + admin endpoint
  for Cloud Scheduler.
"""
from __future__ import annotations




def test_sqlite_busy_timeout_configured(app):
    """Both binds (default = stations, 'users' = users.db) must declare
    a 30 s connect_args timeout. Without it gcsfuse fsync latency on
    Cloud Run can exceed the 5 s default and surface as
    `OperationalError: database is locked` 500s under bursty writes."""
    opts = app.config.get('SQLALCHEMY_ENGINE_OPTIONS') or {}
    assert opts.get('connect_args', {}).get('timeout') == 30
    bind_opts = app.config.get('SQLALCHEMY_BINDS_ENGINE_OPTIONS') or {}
    users_opts = bind_opts.get('users', {})
    assert users_opts.get('connect_args', {}).get('timeout') == 30


def test_purge_helper_is_idempotent(app):
    """Calling the retention helper twice in a row must succeed both
    times — the second call has nothing to do but mustn't crash."""
    from database import db
    from api_access import purge_submit_location_events_older_than_30_days
    with app.app_context():
        engine = db.get_engine(app, bind='users')
        n1 = purge_submit_location_events_older_than_30_days(engine)
        n2 = purge_submit_location_events_older_than_30_days(engine)
        assert isinstance(n1, int) and n1 >= 0
        assert n2 == 0  # nothing left after first call


def test_retention_endpoint_requires_auth(client):
    """No bearer + no admin session → 401."""
    r = client.post("/admin/run_retention", headers={"Referer": "http://localhost/"})
    assert r.status_code == 401


def test_retention_endpoint_accepts_bearer_token(client, app):
    """Cloud Scheduler invocation path: Authorization bearer matching
    settings.metrics_bearer_token works without a session.

    settings is a frozen dataclass so we use object.__setattr__ to
    plant the test value rather than monkeypatch.setattr (which would
    raise FrozenInstanceError).
    """
    import app as app_module
    object.__setattr__(app_module.settings, "metrics_bearer_token",
                       "secret-cron-token")
    try:
        r = client.post(
            "/admin/run_retention",
            headers={
                "Authorization": "Bearer secret-cron-token",
                "Referer": "http://localhost/",
            },
        )
        assert r.status_code == 200, r.data
        body = r.get_json() or {}
        assert body.get("success") is True
        assert "deleted" in body
    finally:
        # Restore so other tests aren't poisoned.
        object.__setattr__(app_module.settings, "metrics_bearer_token", "")


def test_retention_endpoint_rejects_wrong_bearer(client):
    """Bearer that doesn't match settings.metrics_bearer_token falls
    back to the admin-session check — anonymous → 401."""
    import app as app_module
    object.__setattr__(app_module.settings, "metrics_bearer_token",
                       "right-token")
    try:
        r = client.post(
            "/admin/run_retention",
            headers={
                "Authorization": "Bearer wrong-token",
                "Referer": "http://localhost/",
            },
        )
        assert r.status_code == 401
    finally:
        object.__setattr__(app_module.settings, "metrics_bearer_token", "")
