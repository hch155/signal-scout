"""Centralized config — every environment variable is read here."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "t")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """Frozen so accidental late-mutation in routes raises AttributeError."""

    # ── Runtime mode ──
    env: str = field(default_factory=lambda: _str("ENV", "development"))
    debug: bool = field(default_factory=lambda: _bool("FLASK_DEBUG"))
    port: int = field(default_factory=lambda: _int("PORT", 8080))

    # ── Crypto ──
    secret_key: str = field(default_factory=lambda: _str("SECRET_KEY") or secrets.token_hex(32))

    # ── Storage paths ──
    stations_db_path: Optional[str] = field(default_factory=lambda: _str("STATIONS_DB_PATH") or None)
    users_db_path: Optional[str] = field(default_factory=lambda: _str("USERS_DB_PATH") or None)
    addresses_db_path: Optional[str] = field(default_factory=lambda: _str("ADDRESSES_DB_PATH") or None)
    session_file_dir: Optional[str] = field(default_factory=lambda: _str("SESSION_FILE_DIR") or None)

    # ── Session policy ──
    session_lifetime: timedelta = field(default_factory=lambda: timedelta(days=7))

    # ── Observability ──
    metrics_bearer_token: str = field(default_factory=lambda: _str("METRICS_BEARER_TOKEN"))
    app_version: str = field(default_factory=lambda: _str("APP_VERSION", "dev"))
    repo_url: str = field(default_factory=lambda: _str(
        "REPO_URL", "https://github.com/hch155/signal-scout"))

    # ── Honeypot ──
    honeypot_bts_ids_raw: str = field(default_factory=lambda: _str("HONEYPOT_BTS_IDS"))

    # ── Transactional email ──
    email_backend: str = field(default_factory=lambda: _str("EMAIL_BACKEND", "noop").lower())
    email_from: str = field(default_factory=lambda: _str("EMAIL_FROM", "hello@signal-scout.com"))
    email_from_name: str = field(default_factory=lambda: _str("EMAIL_FROM_NAME", "Signal-Scout"))
    sendgrid_api_key: str = field(default_factory=lambda: _str("SENDGRID_API_KEY"))
    glitchtip_dsn: str = field(default_factory=lambda: _str("GLITCHTIP_DSN"))
    sendgrid_webhook_public_key: str = field(default_factory=lambda: _str("SENDGRID_WEBHOOK_PUBLIC_KEY"))
    smtp_host: str = field(default_factory=lambda: _str("SMTP_HOST", "127.0.0.1"))
    smtp_port: int = field(default_factory=lambda: int(_str("SMTP_PORT", "1025") or "1025"))
    smtp_username: str = field(default_factory=lambda: _str("SMTP_USERNAME"))
    smtp_password: str = field(default_factory=lambda: _str("SMTP_PASSWORD"))
    smtp_use_tls: bool = field(default_factory=lambda: _str("SMTP_USE_TLS", "").lower() in ("1", "true", "yes"))

    # ── Admin ──
    admin_emails_raw: str = field(default_factory=lambda: _str("ADMIN_EMAILS"))

    # ── OAuth providers ──
    google_oauth_client_id: str = field(default_factory=lambda: _str("GOOGLE_OAUTH_CLIENT_ID"))
    google_oauth_client_secret: str = field(default_factory=lambda: _str("GOOGLE_OAUTH_CLIENT_SECRET"))
    github_oauth_client_id: str = field(default_factory=lambda: _str("GITHUB_OAUTH_CLIENT_ID"))
    github_oauth_client_secret: str = field(default_factory=lambda: _str("GITHUB_OAUTH_CLIENT_SECRET"))
    facebook_oauth_client_id: str = field(default_factory=lambda: _str("FACEBOOK_OAUTH_CLIENT_ID"))
    facebook_oauth_client_secret: str = field(default_factory=lambda: _str("FACEBOOK_OAUTH_CLIENT_SECRET"))

    # ── KMS (at-rest encryption for TOTP secret) ──
    gcp_kms_key_name: str = field(default_factory=lambda: _str("GCP_KMS_KEY_NAME"))

    # ── Embed widget ──
    embed_allowed_origins_raw: str = field(default_factory=lambda: _str("EMBED_ALLOWED_ORIGINS"))

    # ── SEO ──
    canonical_origin: str = field(default_factory=lambda: _str("CANONICAL_ORIGIN", "https://www.signal-scout.com"))
    marketing_enabled: bool = field(default_factory=lambda: _str("MARKETING_ENABLED", "").lower() in ("1", "true", "yes", "on"))
    email_link_origin: str = field(default_factory=lambda: _str("EMAIL_LINK_ORIGIN", "https://signal-scout.com"))

    # ── Derived properties ──
    @property
    def is_production(self) -> bool:
        return self.env.strip().upper() == "PRODUCTION"

    @property
    def cookie_secure(self) -> bool:
        return self.is_production

    @property
    def static_max_age(self) -> int:
        return 31_536_000 if self.is_production else 0

    @property
    def app_version_sha(self) -> str:
        """'2026.04.24-a3f9c12' → 'a3f9c12'; '' for unparseable values."""
        if "-" in self.app_version:
            tail = self.app_version.rsplit("-", 1)[1]
            if len(tail) == 7 and all(c in "0123456789abcdef" for c in tail):
                return tail
        return ""

    @property
    def honeypot_bts_ids(self) -> set[str]:
        return {x.strip().upper() for x in self.honeypot_bts_ids_raw.split(",") if x.strip()}

    @property
    def embed_allowed_origins(self) -> list[str]:
        return [x.strip() for x in self.embed_allowed_origins_raw.split(",") if x.strip()]

    @property
    def admin_emails(self) -> set[str]:
        return {x.strip().lower() for x in self.admin_emails_raw.split(",") if x.strip()}


settings = Config()


# Refuse to boot in production without a stable SECRET_KEY (else every restart
# invalidates all signed cookies and logs users out).
if settings.is_production and not _str("SECRET_KEY"):
    raise RuntimeError("SECRET_KEY environment variable is required when ENV=PRODUCTION.")
