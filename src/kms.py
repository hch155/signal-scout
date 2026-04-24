"""KMS envelope encryption for at-rest secrets.

Threat model: SQLite users.db lives on a GCS bucket mounted via gcsfuse.
A bucket compromise (stolen GCP credentials, leaked backup, misconfigured
IAM) would otherwise hand the attacker every TOTP secret in plaintext —
they could log in as any 2FA-enabled user without the user's authenticator
ever seeing it. KMS pushes the wrapping key into a managed HSM that the
app can ask to encrypt/decrypt but never gets a copy of, so a stolen
database alone is useless.

Design:
- `KmsBackend` is the small surface (`encrypt(bytes) -> bytes`,
  `decrypt(bytes) -> bytes`). Two concrete impls:
  - `NoopKms`: passthrough. Default in dev/tests where setting up a real
    KMS keyring is friction. Same byte in, same byte out.
  - `GoogleKmsBackend`: calls `google-cloud-kms` against the key named in
    `GCP_KMS_KEY_NAME`. Lazy-imports the client so dev installs without
    google-cloud-kms still boot.
- `get_kms()` is the per-process singleton — first call binds the backend
  based on env, subsequent calls return the same instance. Backend choice
  is fixed at import time on purpose: switching mid-flight would mean
  half the rows in one format and half in another with no way to tell.

Activation in prod:
1. `gcloud kms keyrings create signal-scout --location=europe-central2`
2. `gcloud kms keys create totp-wrap --keyring=signal-scout
   --location=europe-central2 --purpose=encryption`
3. Grant the Cloud Run runtime SA `roles/cloudkms.cryptoKeyEncrypterDecrypter`
   on that key.
4. Set `GCP_KMS_KEY_NAME=projects/.../keyRings/signal-scout/cryptoKeys/totp-wrap`
   in the cd.yaml env block. Next deploy flips the backend.

No new TOTP secret is written in plaintext after activation. Existing rows
keep their plaintext `User.totp_secret` until the next regenerate; the
read path falls back through it transparently.
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


class GoogleKmsBackend(KmsBackend):
    """Calls Google Cloud KMS. Constructed lazily — instantiating the
    client requires google-auth credentials and a network round-trip, so
    we only do that when KMS is actually configured."""

    name = "gcp"

    def __init__(self, key_name: str) -> None:
        # Lazy import: dev environments don't need google-cloud-kms
        # installed unless they set GCP_KMS_KEY_NAME.
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
    """Process-singleton. First call binds the backend based on the
    GCP_KMS_KEY_NAME env (read via config.settings)."""
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
            # Fail closed — if KMS was configured but the client can't
            # initialise (missing google-cloud-kms install, no creds),
            # crashing here is better than silently writing plaintext
            # secrets to a "supposedly encrypted" column.
            logger.exception(
                "KMS configured (GCP_KMS_KEY_NAME set) but client init "
                "failed — refusing to fall back to NoopKms in prod."
            )
            raise
    else:
        _BACKEND = NoopKms()
        logger.info("KMS inactive: backend=noop (set GCP_KMS_KEY_NAME to enable)")
    return _BACKEND


def reset_for_tests() -> None:
    """Drop the cached backend so tests can swap envs and re-bind."""
    global _BACKEND
    _BACKEND = None
