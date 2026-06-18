"""GlitchTip/Sentry before_send scrubbing — no user data leaves the box.

Depends on the `app` fixture only so src/ is importable + env is set; the
function under test is pure (no app context needed)."""
import pytest

pytestmark = pytest.mark.integration


def test_scrub_strips_query_ip_cookies_user(app):
    from app import _scrub_sentry_event

    event = {
        "request": {
            "url": "https://signal-scout.com/api/v1/stations?lat=52.23&lng=21.0",
            "query_string": "lat=52.23&lng=21.0",
            "cookies": {"session": "secret", "ss_sid": "abc"},
            "data": {"password": "hunter2"},
            "headers": {
                "Cookie": "session=secret",
                "X-Forwarded-For": "203.0.113.5",
                "X-Api-Key": "sk_live_x",
                "User-Agent": "Mozilla/5.0",
            },
            "env": {"REMOTE_ADDR": "203.0.113.5", "SERVER_NAME": "app"},
        },
        "user": {"id": 42, "email": "a@b.com", "ip_address": "203.0.113.5"},
        "exception": {"values": [{"type": "ValueError"}]},
    }

    out = _scrub_sentry_event(event, {})
    req = out["request"]

    # Coordinates gone from URL + query string.
    assert "?" not in req["url"]
    assert req["query_string"] == ""
    # IP / cookies / tokens / body gone.
    assert "cookies" not in req
    assert "data" not in req
    assert "X-Forwarded-For" not in req["headers"]
    assert "X-Api-Key" not in req["headers"]
    assert "Cookie" not in req["headers"]
    assert "REMOTE_ADDR" not in req["env"]
    # Non-sensitive context kept (so the error is still debuggable).
    assert req["headers"]["User-Agent"] == "Mozilla/5.0"
    assert req["env"]["SERVER_NAME"] == "app"
    # No user identity.
    assert "user" not in out
    # The actual error survives.
    assert out["exception"]["values"][0]["type"] == "ValueError"


def test_scrub_handles_missing_request(app):
    from app import _scrub_sentry_event
    assert _scrub_sentry_event({"exception": {}}, {}) == {"exception": {}}
