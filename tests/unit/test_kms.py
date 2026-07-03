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
    GCP_KMS_KEY_NAME / SECRET_KEY envs. After the test runs, restore the
    session's original SECRET_KEY BEFORE reloading config — monkeypatch
    only undoes env changes after this teardown, and reloading config
    while SECRET_KEY is deleted would mint a random per-reload secret
    that breaks signature round-trips (unsubscribe tokens) in every
    later test whose signer captured the original settings object."""
    import os
    orig_secret = os.environ.get("SECRET_KEY")
    yield
    monkeypatch.delenv("GCP_KMS_KEY_NAME", raising=False)
    if orig_secret is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", orig_secret)
    import config
    importlib.reload(config)
    import kms as kms_mod
    importlib.reload(kms_mod)
    kms_mod.reset_for_tests()
    # Re-bind the symbol auth_routes captured at import time.
    import auth_routes
    auth_routes.get_kms = kms_mod.get_kms


def _reset(monkeypatch, env_value: str | None, secret_key: str | None = None):
    """Reset config + KMS singletons so tests can swap GCP_KMS_KEY_NAME
    and SECRET_KEY (which selects the FernetKms backend when set)."""
    if env_value is None:
        monkeypatch.delenv("GCP_KMS_KEY_NAME", raising=False)
    else:
        monkeypatch.setenv("GCP_KMS_KEY_NAME", env_value)
    if secret_key is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", secret_key)
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


def test_fernet_backend_selected_when_secret_key_set(monkeypatch):
    kms_mod = _reset(monkeypatch, None, secret_key="s" * 64)
    backend = kms_mod.get_kms()
    assert backend.name == "fernet"
    assert backend.is_active is True

    plaintext = b"JBSWY3DPEHPK3PXP"
    ct = backend.encrypt(plaintext)
    assert ct != plaintext
    assert backend.decrypt(ct) == plaintext


def test_fernet_decrypt_passthrough_for_legacy_noop_bytes(monkeypatch):
    """Rows wrapped by the earlier NoopKms hold the raw secret bytes.
    FernetKms.decrypt must hand those back unchanged so legacy 2FA
    users keep logging in until the boot re-wrap upgrades the row."""
    kms_mod = _reset(monkeypatch, None, secret_key="s" * 64)
    backend = kms_mod.get_kms()
    legacy = b"JBSWY3DPEHPK3PXP"
    assert backend.decrypt(legacy) == legacy


def test_fernet_keys_differ_per_secret(monkeypatch):
    kms_mod = _reset(monkeypatch, None, secret_key="a" * 64)
    ct = kms_mod.get_kms().encrypt(b"topsecret")
    kms_mod = _reset(monkeypatch, None, secret_key="b" * 64)
    other = kms_mod.get_kms()
    assert other.decrypt(ct) == ct  # wrong key -> passthrough, not plaintext
