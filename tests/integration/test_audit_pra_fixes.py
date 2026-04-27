"""Regression coverage for re-audit batch PR A:
- L-NEW-3: refuse to boot in production when SECRET_KEY is missing.
- M-NEW-4: bcrypt timing leak — login response time must be the same
  shape regardless of whether the email exists.
"""
from __future__ import annotations

import os
import time

import pytest


# ───────────────────────────────────────────────────────────────────
# L-NEW-3: SECRET_KEY required in production
# ───────────────────────────────────────────────────────────────────

def test_config_refuses_to_boot_production_without_secret_key(monkeypatch):
    """Importing config when ENV=PRODUCTION and SECRET_KEY is missing
    must raise — not silently fall back to a per-process random key
    (which invalidates every itsdangerous-signed cookie on next boot)."""
    monkeypatch.setenv("ENV", "PRODUCTION")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    # Force re-import so the module-level `settings = Config()` re-runs
    # with the patched environment.
    import importlib
    import sys
    sys.modules.pop("config", None)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        importlib.import_module("config")
    # Restore module so other tests get a healthy `config` import.
    sys.modules.pop("config", None)
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    importlib.import_module("config")


def test_config_boots_in_dev_without_secret_key(monkeypatch):
    """Sanity: dev / test environments still get the random-fallback."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    import importlib
    import sys
    sys.modules.pop("config", None)
    cfg = importlib.import_module("config")
    assert cfg.settings.secret_key  # generated random
    sys.modules.pop("config", None)


# ───────────────────────────────────────────────────────────────────
# M-NEW-4: bcrypt timing leak on missing user
# ───────────────────────────────────────────────────────────────────

def _measure_login_ms(client, email: str, password: str = "Aa1!aaaaaa",
                      csrf: str = "test-csrf-token", samples: int = 5) -> float:
    """Median wall-clock for /login of given email. Median over N
    samples to swallow GC noise."""
    timings = []
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf
    for _ in range(samples):
        t0 = time.perf_counter()
        client.post("/login", data={
            "_csrf_token": csrf, "email": email, "password": password,
        })
        timings.append((time.perf_counter() - t0) * 1000)
    timings.sort()
    return timings[len(timings) // 2]


def test_login_for_missing_user_burns_bcrypt_round(client, csrf_token, app):
    """Login for a non-existent email must spend roughly the same time
    as a login for an existing email with a wrong password — both
    should pay one bcrypt round. Without the fix, missing-user is
    ~5 ms and existing-user is ~80 ms (12-rounds bcrypt), distinguishable
    in a few samples.

    We assert that the missing-user path takes at least 30 ms — well
    above the no-bcrypt baseline and a fair lower bound for any modern
    bcrypt(rounds=12). Don't assert tight equality with the existing-
    user path: CI noise + first-call import overhead make absolute
    comparisons flaky. The lower bound alone proves a bcrypt round
    actually executed.
    """
    from auth_routes import _bcrypt
    # Warm the bcrypt module (first call has Python-side import cost).
    with app.app_context():
        _bcrypt().check_password_hash(
            '$2b$12$wFRtPM8VvZdEdBbY5lJ4ZeEf4eXIYlD0d1yhxwOO5Z3cV1Mv8qC.O',
            'warmup',
        )

    missing_ms = _measure_login_ms(
        client, "nobody-here@example.com", csrf=csrf_token, samples=3,
    )
    # bcrypt(rounds=12) on modern CPUs is ~50-150ms per check. 30ms
    # floor is conservative — a no-op response would be ~5ms.
    assert missing_ms > 30, (
        f"login for missing user returned in {missing_ms:.1f} ms — "
        "no bcrypt round was burned. M-NEW-4 fix regressed."
    )
