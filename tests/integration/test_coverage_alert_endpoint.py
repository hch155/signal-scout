"""Coverage for /admin/run_coverage_alerts (Cloud-Scheduler-callable
trigger added 2026-04-28)."""
from __future__ import annotations

import json as _json


def test_endpoint_requires_auth(client):
    """Anon → 401."""
    r = client.post("/admin/run_coverage_alerts",
                    headers={"Referer": "http://localhost/"})
    assert r.status_code == 401


def test_endpoint_accepts_bearer_token_dry_run(client, app):
    """Bearer + ?dry-run=1 returns 200 with counts dict (and zero
    sent because the test DB has no alerting-enabled locations)."""
    import app as app_module
    object.__setattr__(app_module.settings, "metrics_bearer_token",
                       "test-bearer-cov")
    try:
        r = client.post(
            "/admin/run_coverage_alerts?dry-run=1",
            headers={
                "Authorization": "Bearer test-bearer-cov",
                "Referer": "http://localhost/",
            },
        )
        assert r.status_code == 200, r.data
        body = r.get_json() or {}
        assert body.get("success") is True
        assert body.get("dry_run") is True
        counts = body.get("counts") or {}
        for k in ('first-run', 'no-change', 'sent', 'send-failed',
                  'skipped', 'total_processed'):
            assert k in counts
    finally:
        object.__setattr__(app_module.settings, "metrics_bearer_token", "")


def test_endpoint_rejects_wrong_bearer(client):
    import app as app_module
    object.__setattr__(app_module.settings, "metrics_bearer_token",
                       "right-cov-token")
    try:
        r = client.post(
            "/admin/run_coverage_alerts",
            headers={
                "Authorization": "Bearer wrong-token",
                "Referer": "http://localhost/",
            },
        )
        assert r.status_code == 401
    finally:
        object.__setattr__(app_module.settings, "metrics_bearer_token", "")
