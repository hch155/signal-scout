"""ENV parsing — regression tests for audit finding N1 (2026-06-10).

`is_production` used to require the literal uppercase "PRODUCTION", while
the CI/CD pipeline writes `ENV=production` (lowercase) into the prod .env.
The mismatch silently flipped is_production to False in production, which
(a) dropped the Secure flag from session cookies and (b) bypassed the
SECRET_KEY fail-fast boot guard (audit fix L-NEW-3). These tests pin the
case-insensitive behaviour.

Import note: `config` builds a module-level `settings` singleton from the
environment at import time, so each case reloads the module under a
patched env and restores the original afterwards.
"""
import importlib

import pytest


@pytest.fixture
def reload_config(monkeypatch):
    import config

    def _reload(env_value, secret_key="test-secret"):
        monkeypatch.setenv("ENV", env_value)
        if secret_key is None:
            monkeypatch.delenv("SECRET_KEY", raising=False)
        else:
            monkeypatch.setenv("SECRET_KEY", secret_key)
        return importlib.reload(config)

    yield _reload
    monkeypatch.undo()
    importlib.reload(config)


@pytest.mark.unit
@pytest.mark.parametrize("env_value", ["PRODUCTION", "production", "Production", " production "])
def test_is_production_case_insensitive(reload_config, env_value):
    cfg = reload_config(env_value)
    assert cfg.settings.is_production is True
    assert cfg.settings.cookie_secure is True


@pytest.mark.unit
@pytest.mark.parametrize("env_value", ["development", "staging", ""])
def test_non_production_envs(reload_config, env_value):
    cfg = reload_config(env_value)
    assert cfg.settings.is_production is False
    assert cfg.settings.cookie_secure is False


@pytest.mark.unit
def test_secret_key_guard_fires_for_lowercase_production(reload_config):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        reload_config("production", secret_key=None)
