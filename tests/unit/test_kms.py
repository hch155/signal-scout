"""PR #39: KMS backend smoke tests.

Pure unit tests — no Flask, no DB. Verifies:
- NoopKms is a true round-trip (passthrough), since the entire dev/test
  story rests on it being indistinguishable from "no encryption".
- get_kms() picks NoopKms when GCP_KMS_KEY_NAME is empty.
- get_kms() is cached per process — switching env after the first call
  doesn't quietly swap backends mid-flight (would silently corrupt
  encrypted columns).
- TypeError surfaces on non-bytes input — catches accidental
  encrypt(str) calls before they hit prod.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _isolate_kms_module(monkeypatch):
    """Each test in this file reloads `config` and `kms` to swap the
    GCP_KMS_KEY_NAME env. After the test runs, reload them back with
    the env un-set so the next test (in any other file) sees the
    original NoopKms backend rather than a sticky GoogleKmsBackend
    attempt that fails the lazy import."""
    yield
    monkeypatch.delenv("GCP_KMS_KEY_NAME", raising=False)
    import config
    importlib.reload(config)
    import kms as kms_mod
    importlib.reload(kms_mod)
    kms_mod.reset_for_tests()
    # Re-bind the symbol auth_routes captured at import time.
    import auth_routes
    auth_routes.get_kms = kms_mod.get_kms


def _reset(monkeypatch, env_value: str | None):
    """Reset config + KMS singletons so tests can swap GCP_KMS_KEY_NAME."""
    if env_value is None:
        monkeypatch.delenv("GCP_KMS_KEY_NAME", raising=False)
    else:
        monkeypatch.setenv("GCP_KMS_KEY_NAME", env_value)
    import config
    importlib.reload(config)
    import kms as kms_mod
    importlib.reload(kms_mod)
    return kms_mod


def test_noop_kms_roundtrip(monkeypatch):
    kms_mod = _reset(monkeypatch, None)
    backend = kms_mod.get_kms()
    assert backend.name == "noop"
    assert backend.is_active is False

    plaintext = b"JBSWY3DPEHPK3PXP"  # base32 — what pyotp produces
    ct = backend.encrypt(plaintext)
    assert backend.decrypt(ct) == plaintext


def test_noop_passthrough_is_identity(monkeypatch):
    """Passthrough must be byte-identical so the wire format is stable
    regardless of which backend last touched the row."""
    kms_mod = _reset(monkeypatch, None)
    backend = kms_mod.get_kms()
    for sample in (b"", b"x", b"a" * 1024):
        assert backend.encrypt(sample) == sample
        assert backend.decrypt(sample) == sample


def test_get_kms_is_cached(monkeypatch):
    kms_mod = _reset(monkeypatch, None)
    a = kms_mod.get_kms()
    b = kms_mod.get_kms()
    assert a is b


def test_get_kms_resets_for_tests(monkeypatch):
    kms_mod = _reset(monkeypatch, None)
    a = kms_mod.get_kms()
    kms_mod.reset_for_tests()
    b = kms_mod.get_kms()
    assert a is not b
    # Both still NoopKms because env hasn't changed.
    assert b.name == "noop"


def test_encrypt_rejects_non_bytes(monkeypatch):
    kms_mod = _reset(monkeypatch, None)
    backend = kms_mod.get_kms()
    with pytest.raises(TypeError):
        backend.encrypt("not bytes")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        backend.decrypt("not bytes")  # type: ignore[arg-type]


def test_get_kms_with_env_attempts_gcp_init(monkeypatch):
    """When GCP_KMS_KEY_NAME is set, get_kms() must NOT silently fall back
    to NoopKms — that would write plaintext into a "supposedly encrypted"
    column. Without google-cloud-kms installed in the test env, the
    GoogleKmsBackend constructor's lazy import raises ImportError and
    get_kms() should propagate (fail-closed)."""
    kms_mod = _reset(
        monkeypatch,
        "projects/test/locations/eu/keyRings/r/cryptoKeys/k",
    )
    with pytest.raises(Exception):
        kms_mod.get_kms()
