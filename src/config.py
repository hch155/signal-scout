"""Centralized config — single place where every environment variable is read.

Before this module: env reads were scattered across app.py, observability.py,
api_access.py, api_docs.py. Adding new vars meant grepping all of them and
debugging "why isn't it picking up". After: one Config dataclass; modules
import named attributes.

Convention: every config key has a typed attribute, a sensible default for
local dev, and an inline note on what it controls. New vars go here only.
Don't import os.getenv anywhere else (api_access._load_honeypot_ids is the
one exception — it intentionally reloads at runtime for tests).
"""

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

    # ── Runtime mode ─────────────────────────────────────────────────────
    env: str = field(default_factory=lambda: _str("ENV", "development"))
    debug: bool = field(default_factory=lambda: _bool("FLASK_DEBUG"))
    port: int = field(default_factory=lambda: _int("PORT", 8080))

    # ── Crypto ───────────────────────────────────────────────────────────
    # Random per-process default is fine for dev (no shared sessions);
    # production MUST set this via env or sessions disappear on every deploy.
    secret_key: str = field(default_factory=lambda: _str("SECRET_KEY") or secrets.token_hex(32))

    # ── Storage paths ────────────────────────────────────────────────────
    stations_db_path: Optional[str] = field(default_factory=lambda: _str("STATIONS_DB_PATH") or None)
    users_db_path: Optional[str] = field(default_factory=lambda: _str("USERS_DB_PATH") or None)
    session_file_dir: Optional[str] = field(default_factory=lambda: _str("SESSION_FILE_DIR") or None)

    # ── Session policy ───────────────────────────────────────────────────
    session_lifetime: timedelta = field(default_factory=lambda: timedelta(days=7))

    # ── Observability ────────────────────────────────────────────────────
    metrics_bearer_token: str = field(default_factory=lambda: _str("METRICS_BEARER_TOKEN"))
    app_version: str = field(default_factory=lambda: _str("APP_VERSION", "dev"))

    # ── Plausible Analytics ──────────────────────────────────────────────
    plausible_domain: str = field(default_factory=lambda: _str("PLAUSIBLE_DOMAIN"))
    plausible_script_url: str = field(default_factory=lambda: _str("PLAUSIBLE_SCRIPT_URL"))

    # ── Honeypot ─────────────────────────────────────────────────────────
    honeypot_bts_ids_raw: str = field(default_factory=lambda: _str("HONEYPOT_BTS_IDS"))

    # ── KMS (at-rest encryption for TOTP secret) ─────────────────────────
    # Full resource name like
    # `projects/<project>/locations/<region>/keyRings/<ring>/cryptoKeys/<key>`.
    # Empty / unset → NoopKms (passthrough); fine for dev + tests, NOT for
    # prod. Setting this in cd.yaml env flips the backend on next deploy
    # without any code change. See src/kms.py for activation steps.
    gcp_kms_key_name: str = field(default_factory=lambda: _str("GCP_KMS_KEY_NAME"))

    # ── Embed widget ────────────────────────────────────────────────────
    # Comma-separated list of origins allowed to iframe /embed/* (sets
    # CSP `frame-ancestors`). Use literal '*' (single entry) to allow any
    # origin — only do this if you really mean public widget.
    # Empty / unset → /embed/* still served, but iframing blocked by
    # `frame-ancestors 'none'` like the rest of the app.
    embed_allowed_origins_raw: str = field(default_factory=lambda: _str("EMBED_ALLOWED_ORIGINS"))

    # ── SEO ─────────────────────────────────────────────────────────────
    # Public canonical origin used in OG / canonical / sitemap. Falls back
    # to https://www.signal-scout.com which matches the apex DNS.
    canonical_origin: str = field(default_factory=lambda: _str("CANONICAL_ORIGIN", "https://www.signal-scout.com"))

    # ── Derived properties ───────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.env == "PRODUCTION"

    @property
    def cookie_secure(self) -> bool:
        """Secure cookie only over HTTPS (prod). Local dev wants False so
        http://localhost sessions work for perf tests."""
        return self.is_production

    @property
    def static_max_age(self) -> int:
        """Long-cache static assets in prod, no cache in dev."""
        return 31_536_000 if self.is_production else 0

    @property
    def honeypot_bts_ids(self) -> set[str]:
        return {x.strip().upper() for x in self.honeypot_bts_ids_raw.split(",") if x.strip()}

    @property
    def embed_allowed_origins(self) -> list[str]:
        return [x.strip() for x in self.embed_allowed_origins_raw.split(",") if x.strip()]


# Module-level singleton. Imported as `from config import settings`.
settings = Config()
