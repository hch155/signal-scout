"""Envelope encryption for at-rest secrets (TOTP 2FA seeds).

Threat model: the SQLite users.db lives on a persistent volume. A stolen
copy — a leaked backup, host compromise, a snapshot pulled off disk —
would otherwise hand the attacker every TOTP secret in plaintext, letting
them log in as any 2FA-enabled user without ever touching the user's
authenticator. Wrapping the seeds means a stolen database alone is useless:
the wrapping key is never stored beside the data.

Design:
- `KmsBackend` is the small surface (`encrypt(bytes) -> bytes`,
  `decrypt(bytes) -> bytes`). Three concrete impls:
  - `NoopKms`: passthrough. Dev/tests, where standing up real key material
    is pure friction. Same byte in, same byte out.
  - `FernetKms`: the default real backend. AES via Fernet, key derived from
    the explicitly-configured SECRET_KEY through HKDF-SHA256 — no external
    dependency, wrapping key kept out of the DB.
  - `GoogleKmsBackend`: optional HSM path for a Cloud-KMS deployment; calls
    `google-cloud-kms` against `GCP_KMS_KEY_NAME`, lazy-imported so installs
    without the client still boot.
- `get_kms()` is the per-process singleton: first call binds the backend
  from env (Google KMS if `GCP_KMS_KEY_NAME` is set, else Fernet if a
  SECRET_KEY is explicitly configured, else Noop), later calls return it.
  Backend choice is fixed at import time on purpose — switching mid-flight
  would leave half the rows in one format and half in another with no way
  to tell them apart.

Existing plaintext `User.totp_secret` rows are read transparently and only
wrapped on the next regenerate, so enabling a backend needs no migration.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings


logger = logging.getLogger(__name__)


class KmsBackend:
    """Smallest possible surface — pure bytes in, pure bytes out."""

    name: str = "abstract"

    def encrypt(self, plaintext: bytes) -> bytes:  # pragma: no cover - abstract
        raise NotImplementedError

    def decrypt(self, ciphertext: bytes) -> bytes:  # pragma: no cover - abstract
        raise NotImplementedError

    @property
    def is_active(self) -> bool:
        """True when this backend is doing real cryptography. Callers can
        check this to decide whether to log "KMS-protected" in audit
        events vs. silently passthrough."""
        return False


class NoopKms(KmsBackend):
    """Passthrough — used in dev and tests. Returns input unchanged so
    code paths exercise the same wrap/unwrap calls without needing a real
    KMS keyring. NEVER pick this in prod: no encryption is actually done."""

    name = "noop"

    def encrypt(self, plaintext: bytes) -> bytes:
        if not isinstance(plaintext, (bytes, bytearray)):
            raise TypeError("KMS encrypt expects bytes")
        return bytes(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not isinstance(ciphertext, (bytes, bytearray)):
            raise TypeError("KMS decrypt expects bytes")
        return bytes(ciphertext)


class FernetKms(KmsBackend):
    """Local AES-based encryption (Fernet) with a key derived from the
    explicitly-configured SECRET_KEY via HKDF-SHA256. The default real
    backend on self-hosted prod, where no Google KMS keyring exists: a
    stolen users.db alone no longer yields TOTP secrets — the attacker
    also needs the SECRET_KEY from the stack env.

    decrypt() falls back to returning the input unchanged when the bytes
    are not a Fernet token, so rows wrapped by the earlier NoopKms
    (base64 of the raw secret) keep reading transparently until the boot
    re-wrap upgrades them."""

    name = "fernet"

    def __init__(self, secret: str) -> None:
        import base64
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32,
                    salt=b"signal-scout-kms-v1", info=b"totp-wrap")
        key = base64.urlsafe_b64encode(hkdf.derive(secret.encode('utf-8')))
        self._fernet = Fernet(key)

    @property
    def is_active(self) -> bool:
        return True

    def encrypt(self, plaintext: bytes) -> bytes:
        if not isinstance(plaintext, (bytes, bytearray)):
            raise TypeError("KMS encrypt expects bytes")
        return self._fernet.encrypt(bytes(plaintext))

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not isinstance(ciphertext, (bytes, bytearray)):
            raise TypeError("KMS decrypt expects bytes")
        from cryptography.fernet import InvalidToken
        try:
            return self._fernet.decrypt(bytes(ciphertext))
        except InvalidToken:
            return bytes(ciphertext)


class GoogleKmsBackend(KmsBackend):
    """Calls Google Cloud KMS. Constructed lazily — instantiating the
    client requires google-auth credentials and a network round-trip, so
    we only do that when KMS is actually configured."""

    name = "gcp"

    def __init__(self, key_name: str) -> None:
        from google.cloud import kms  # type: ignore
        self._key_name = key_name
        self._client = kms.KeyManagementServiceClient()

    @property
    def is_active(self) -> bool:
        return True

    def encrypt(self, plaintext: bytes) -> bytes:
        if not isinstance(plaintext, (bytes, bytearray)):
            raise TypeError("KMS encrypt expects bytes")
        resp = self._client.encrypt(
            request={"name": self._key_name, "plaintext": bytes(plaintext)}
        )
        return resp.ciphertext

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not isinstance(ciphertext, (bytes, bytearray)):
            raise TypeError("KMS decrypt expects bytes")
        resp = self._client.decrypt(
            request={"name": self._key_name, "ciphertext": bytes(ciphertext)}
        )
        return resp.plaintext


_BACKEND: Optional[KmsBackend] = None


def get_kms() -> KmsBackend:
    """Process-singleton. First call binds the backend: Google KMS when
    GCP_KMS_KEY_NAME is set, else Fernet keyed off an explicitly
    configured SECRET_KEY, else Noop. The SECRET_KEY check reads the
    env directly rather than settings.secret_key on purpose — settings
    falls back to a random per-boot value, and deriving a Fernet key
    from that would make every wrapped row undecryptable after a
    restart."""
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    key_name = settings.gcp_kms_key_name
    if key_name:
        try:
            _BACKEND = GoogleKmsBackend(key_name)
            logger.info("KMS active: backend=gcp key_name=%s",
                        key_name.rsplit('/', 1)[-1])
        except Exception:
            logger.exception(
                "KMS configured (GCP_KMS_KEY_NAME set) but client init "
                "failed — refusing to fall back to NoopKms in prod."
            )
            raise
        return _BACKEND
    import os
    explicit_secret = (os.getenv("SECRET_KEY") or "").strip()
    if explicit_secret:
        _BACKEND = FernetKms(explicit_secret)
        logger.info("KMS active: backend=fernet (derived from SECRET_KEY)")
    else:
        _BACKEND = NoopKms()
        logger.info("KMS inactive: backend=noop (set GCP_KMS_KEY_NAME "
                    "or SECRET_KEY to enable)")
    return _BACKEND


def reset_for_tests() -> None:
    """Drop the cached backend so tests can swap envs and re-bind."""
    global _BACKEND
    _BACKEND = None
