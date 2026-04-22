"""Rate limit regressions.

Marked @pytest.mark.slow because they hammer the rate-limited endpoints in a
tight loop. Default `pytest` invocation excludes them; opt in with `-m slow`.
"""
import json
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

WARSAW = (52.2297, 21.0122)


def test_stations_30_per_minute_then_429(client):
    """/stations is documented at 30/min — 31st in a minute returns 429."""
    last_status = None
    for i in range(31):
        r = client.get(f"/stations?lat={WARSAW[0]}&lng={WARSAW[1]}&limit=1")
        last_status = r.status_code
        if last_status == 429:
            break
    assert last_status == 429


def test_login_3_per_minute_then_429(csrf_client, csrf_token):
    last_status = None
    for i in range(4):
        r = csrf_client.post("/login", data={
            "_csrf_token": csrf_token,
            "email": "ratelimit@example.com",
            "password": "WhateverPass1!",
        })
        last_status = r.status_code
        if last_status == 429:
            break
    assert last_status == 429


def test_register_5_per_hour_then_429(csrf_client, csrf_token):
    last_status = None
    for i in range(6):
        r = csrf_client.post("/register", data={
            "_csrf_token": csrf_token,
            "email": f"rl-{i}@example.com",
            "password": "Aa1!aaaaaa",
            "confirm_password": "Aa1!aaaaaa",
        })
        last_status = r.status_code
        if last_status == 429:
            break
    assert last_status == 429


def test_429_response_uses_html_body(client):
    """Hit the global limiter (16/min default) on a non-explicitly-limited
    route so the 429 handler renders the HTML message."""
    last = None
    for i in range(20):
        last = client.get("/session_check")
        if last.status_code == 429:
            break
    assert last.status_code == 429
    body = last.get_data(as_text=True)
    assert "Rate Limit Exceeded" in body
