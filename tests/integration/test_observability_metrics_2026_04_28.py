"""Coverage for the 2026-04-28 observability expansion:
- http_requests_total{method,endpoint,status,user_class}
- http_request_duration_seconds{method,endpoint}
- user_action_total{action,user_class} bumped from _audit() mapping
  + explicit submit_location / register / OAuth login sites
- request_user_class() helper bucket
"""
from __future__ import annotations

import json as _json


def _scrape_metrics(client, monkeypatch) -> str:
    """Pull /metrics with the bearer token. The view reads
    METRICS_BEARER_TOKEN directly from os.getenv at request time, so
    monkeypatch.setenv is the right tool here."""
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "test-bearer-x")
    r = client.get(
        "/metrics",
        headers={"Authorization": "Bearer test-bearer-x",
                 "Referer": "http://localhost/"},
    )
    assert r.status_code == 200, r.data
    return r.get_data(as_text=True)


def test_http_requests_total_present_after_request(client, monkeypatch):
    """One GET to /data must surface a series with status=2xx."""
    client.get("/data", headers={"Referer": "http://localhost/"})
    body = _scrape_metrics(client, monkeypatch)
    assert "signal_scout_http_requests_total" in body
    # Look for the line that includes endpoint="data_page" + status="2xx".
    # Label order is alphabetical in prometheus_client output:
    # endpoint, method, status, user_class.
    found = any(
        'endpoint="data_page"' in line and 'status="2xx"' in line
        and "signal_scout_http_requests_total" in line
        for line in body.splitlines()
    )
    assert found, "no http_requests_total series for endpoint=data_page status=2xx"


def test_http_request_duration_histogram_present(client, monkeypatch):
    """The duration histogram must record samples per endpoint."""
    client.get("/data", headers={"Referer": "http://localhost/"})
    body = _scrape_metrics(client, monkeypatch)
    assert "signal_scout_http_request_duration_seconds" in body
    # Histogram emits _bucket / _count / _sum lines per label set.
    assert "signal_scout_http_request_duration_seconds_count" in body


def test_user_action_total_bumped_via_audit_mapping(authed_client,
                                                     csrf_token,
                                                     client,
                                                     monkeypatch,
                                                     app):
    """A successful POST /account/profile fires _audit('profile.updated')
    which the new map turns into user_action_total{action='profile_update'}."""
    r = authed_client.post(
        "/account/profile",
        data={"_csrf_token": csrf_token, "company": "Acme"},
        headers={"X-CSRF-Token": csrf_token,
                 "Referer": "http://localhost/"},
    )
    assert r.status_code == 200, r.data

    body = _scrape_metrics(client, monkeypatch)
    assert "signal_scout_user_action_total" in body
    assert any(
        'action="profile_update"' in line
        and "signal_scout_user_action_total" in line
        for line in body.splitlines()
    ), "user_action_total{action='profile_update'} missing — audit→action map regressed"


def test_user_action_total_submit_location_with_user_class(client,
                                                            monkeypatch,
                                                            csrf_token):
    """Anon /submit_location must bump user_action_total with
    user_class='anon'."""
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post(
        "/submit_location",
        data=_json.dumps({"lat": 52.23, "lng": 21.0, "limit": 5}),
        content_type="application/json",
        headers={"X-CSRF-Token": csrf_token,
                 "Referer": "http://localhost/"},
    )
    assert r.status_code == 200, r.data

    body = _scrape_metrics(client, monkeypatch)
    assert any(
        'action="submit_location"' in line
        and 'user_class="anon"' in line
        and "signal_scout_user_action_total" in line
        for line in body.splitlines()
    )


def test_request_user_class_buckets():
    """The helper must return a stable string regardless of context."""
    import app as app_module
    with app_module.app.test_request_context("/"):
        from observability import request_user_class
        assert request_user_class() == "anon"
