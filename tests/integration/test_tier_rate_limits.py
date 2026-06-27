"""End-to-end enforcement of the tier callables through Flask-Limiter.

Builds a throwaway app whose single route stacks a stand-in for
``require_api_access`` (outer — sets ``g.api_tier`` / ``g.api_key_user_id``
from request headers) over ``@limiter.limit(tier_limit_string,
key_func=tier_key_func)`` (inner), the exact ordering the coverage endpoints
must adopt. Proves quotas are enforced per API key (not per IP) and that a
higher tier clears a lower tier's ceiling. Self-contained so it does not
depend on the (returned, not applied) app.py wiring.
"""

import functools

import pytest
from flask import Flask, g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ratelimit import tier_key_func, tier_limit_string

pytestmark = pytest.mark.integration


def _tier_gate(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        g.api_tier = request.headers.get("X-Tier", "anonymous")
        user_id = request.headers.get("X-User-Id")
        if user_id:
            g.api_key_user_id = int(user_id)
        return func(*args, **kwargs)

    return wrapper


@pytest.fixture
def cov_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    limiter = Limiter(app=app, key_func=get_remote_address, storage_uri="memory://")

    @app.route("/cov")
    @_tier_gate
    @limiter.limit(tier_limit_string, key_func=tier_key_func)
    def cov():
        return "ok"

    return app.test_client()


def _headers(tier, user_id=None):
    h = {"X-Tier": tier}
    if user_id is not None:
        h["X-User-Id"] = str(user_id)
    return h


def test_anonymous_tier_blocks_after_ten_per_ip(cov_client):
    for _ in range(10):
        assert cov_client.get("/cov", headers=_headers("anonymous")).status_code == 200
    assert cov_client.get("/cov", headers=_headers("anonymous")).status_code == 429


def test_free_tier_quota_is_per_key_not_per_ip(cov_client):
    for _ in range(60):
        assert cov_client.get("/cov", headers=_headers("free", 1001)).status_code == 200
    assert cov_client.get("/cov", headers=_headers("free", 1001)).status_code == 429
    assert cov_client.get("/cov", headers=_headers("free", 2002)).status_code == 200


def test_higher_tier_clears_lower_tier_ceiling(cov_client):
    for _ in range(70):
        assert cov_client.get("/cov", headers=_headers("pro", 3003)).status_code == 200


def test_keys_are_isolated_across_users(cov_client):
    for _ in range(60):
        assert cov_client.get("/cov", headers=_headers("free", 4004)).status_code == 200
    assert cov_client.get("/cov", headers=_headers("free", 5005)).status_code == 200
    assert cov_client.get("/cov", headers=_headers("free", 4004)).status_code == 429
