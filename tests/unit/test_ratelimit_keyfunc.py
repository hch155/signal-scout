"""Pure-function tests for the tier-aware rate-limit helpers.

Covers the Flask-Limiter key/limit callables (``tier_key_func`` keys by API-key
user id when authenticated, else remote IP; ``tier_limit_string`` reads
``g.api_tier`` and routes it through ``api_access.get_tier_limit``) and the
``memory:// in PRODUCTION`` boot guard. The ``api_access`` dependency is stubbed
for the wiring test so the helpers stay importable without the app database.
"""

import sys
import types

import pytest
from flask import Flask, g

import ratelimit

pytestmark = pytest.mark.unit


@pytest.fixture
def request_ctx():
    app = Flask(__name__)

    def _ctx(remote_addr="203.0.113.7"):
        return app.test_request_context(
            "/coverage_by_address", environ_base={"REMOTE_ADDR": remote_addr}
        )

    return _ctx


def test_keys_by_api_key_user_id_when_authenticated(request_ctx):
    with request_ctx():
        g.api_key_user_id = 42
        assert ratelimit.tier_key_func() == "api_key:42"


def test_falls_back_to_remote_ip_without_api_key(request_ctx):
    with request_ctx(remote_addr="198.51.100.9"):
        assert ratelimit.tier_key_func() == "198.51.100.9"


def test_session_tier_without_key_still_keys_by_ip(request_ctx):
    with request_ctx(remote_addr="198.51.100.9"):
        g.api_tier = "free"
        assert ratelimit.tier_key_func() == "198.51.100.9"


def test_distinct_users_get_distinct_keys(request_ctx):
    with request_ctx():
        g.api_key_user_id = 1
        first = ratelimit.tier_key_func()
    with request_ctx():
        g.api_key_user_id = 2
        second = ratelimit.tier_key_func()
    assert first != second


@pytest.fixture
def stub_api_access(monkeypatch):
    module = types.ModuleType("api_access")
    module.get_tier_limit = lambda tier: f"limit-for-{tier}"
    monkeypatch.setitem(sys.modules, "api_access", module)
    return module


@pytest.mark.parametrize("tier", ["anonymous", "free", "pro", "enterprise"])
def test_limit_string_routes_g_tier_through_api_access(request_ctx, stub_api_access, tier):
    with request_ctx():
        g.api_tier = tier
        assert ratelimit.tier_limit_string() == f"limit-for-{tier}"


def test_limit_string_defaults_to_anonymous_when_tier_unset(request_ctx, stub_api_access):
    with request_ctx():
        assert ratelimit.tier_limit_string() == "limit-for-anonymous"


def test_real_tier_thresholds_match_documented_quotas(request_ctx):
    pytest.importorskip("prometheus_client")
    from api_access import get_tier_limit

    expected = {
        "anonymous": "10 per minute",
        "free": "60 per minute",
        "pro": "300 per minute",
        "enterprise": "3000 per minute",
    }
    for tier, limit in expected.items():
        assert get_tier_limit(tier) == limit
        with request_ctx():
            g.api_tier = tier
            assert ratelimit.tier_limit_string() == limit


@pytest.mark.parametrize("uri", ["memory://", "", "  ", None, "MEMORY://"])
def test_is_memory_storage_true(uri):
    assert ratelimit.is_memory_storage(uri) is True


@pytest.mark.parametrize("uri", ["redis://redis:6379/0", "redis://localhost:6379"])
def test_is_memory_storage_false_for_redis(uri):
    assert ratelimit.is_memory_storage(uri) is False


def test_production_storage_error_flags_memory_in_production():
    msg = ratelimit.production_storage_error("memory://", is_production=True)
    assert msg and "redis" in msg.lower()


def test_production_storage_error_none_for_redis_in_production():
    assert ratelimit.production_storage_error("redis://redis:6379/0", is_production=True) is None


def test_production_storage_error_none_for_memory_in_development():
    assert ratelimit.production_storage_error("memory://", is_production=False) is None


def test_assert_refuses_to_boot_on_memory_in_production():
    with pytest.raises(RuntimeError, match="redis"):
        ratelimit.assert_production_storage("memory://", is_production=True)


def test_assert_warns_without_raising_when_not_strict(caplog):
    with caplog.at_level("WARNING"):
        ratelimit.assert_production_storage("memory://", is_production=True, strict=False)
    assert any("memory://" in r.message for r in caplog.records)


def test_assert_silent_for_redis_in_production():
    ratelimit.assert_production_storage("redis://redis:6379/0", is_production=True)


def test_assert_silent_for_memory_in_development():
    ratelimit.assert_production_storage("memory://", is_production=False)
