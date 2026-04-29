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
    # PR #46.5: footer-rendered build version. Format: `YYYY.MM.DD-<sha7>`
    # (CalVer + 7-char git SHA — Stripe-style date versioning, no SemVer
    # major/minor/patch bookkeeping needed). cd.yaml builds this at deploy
    # time. Local dev → "dev".
    app_version: str = field(default_factory=lambda: _str("APP_VERSION", "dev"))

    # ── Repo URL (footer "version → GitHub commit" link) ─────────────────
    repo_url: str = field(default_factory=lambda: _str(
        "REPO_URL", "https://github.com/hch155/signal-scout"))

    # ── Plausible Analytics ──────────────────────────────────────────────
    plausible_domain: str = field(default_factory=lambda: _str("PLAUSIBLE_DOMAIN"))
    plausible_script_url: str = field(default_factory=lambda: _str("PLAUSIBLE_SCRIPT_URL"))

    # ── Honeypot ─────────────────────────────────────────────────────────
    honeypot_bts_ids_raw: str = field(default_factory=lambda: _str("HONEYPOT_BTS_IDS"))

    # ── Transactional email backend (PR #48 minimal cherry-pick of #249) ─
    # `email_backend` selects which sender to use. Values: "noop" (logs
    # only — default for dev/CI), "smtp" (Mailpit / generic SMTP), or
    # "sendgrid" (SendGrid Web API v3). Backend wiring lives in
    # src/emails.py.
    email_backend: str = field(default_factory=lambda: _str("EMAIL_BACKEND", "noop").lower())
    email_from: str = field(default_factory=lambda: _str("EMAIL_FROM", "noreply@signal-scout.com"))
    email_from_name: str = field(default_factory=lambda: _str("EMAIL_FROM_NAME", "Signal-Scout"))
    sendgrid_api_key: str = field(default_factory=lambda: _str("SENDGRID_API_KEY"))
    # 2026-04-29: ECDSA public key SendGrid uses to sign Event Webhook
    # POSTs. Pasted from Settings → Mail Settings → Event Webhook in
    # SendGrid (the "Verification Key" field after enabling Signed
    # Event Webhook). When unset the /webhooks/sendgrid endpoint
    # returns 503 instead of accepting unsigned events — better to be
    # offline than open to spoofed bounce events.
    sendgrid_webhook_public_key: str = field(default_factory=lambda: _str("SENDGRID_WEBHOOK_PUBLIC_KEY"))
    smtp_host: str = field(default_factory=lambda: _str("SMTP_HOST", "127.0.0.1"))
    smtp_port: int = field(default_factory=lambda: int(_str("SMTP_PORT", "1025") or "1025"))
    smtp_username: str = field(default_factory=lambda: _str("SMTP_USERNAME"))
    smtp_password: str = field(default_factory=lambda: _str("SMTP_PASSWORD"))
    smtp_use_tls: bool = field(default_factory=lambda: _str("SMTP_USE_TLS", "").lower() in ("1", "true", "yes"))

    # ── Admin (PR #48.4) ─────────────────────────────────────────────────
    # Comma-separated emails granted access to /admin/* routes. Stays as
    # a list rather than User.role flag so we can grant access without
    # touching the DB. Empty / unset → /admin/* returns 403 for everyone.
    admin_emails_raw: str = field(default_factory=lambda: _str("ADMIN_EMAILS"))

    # ── OAuth providers (PR #48.7) ───────────────────────────────────────
    # Empty client_id → provider button hidden in /login. So toggling a
    # provider on / off is just a Cloud Run env update + redeploy, no
    # code change.
    google_oauth_client_id: str = field(default_factory=lambda: _str("GOOGLE_OAUTH_CLIENT_ID"))
    google_oauth_client_secret: str = field(default_factory=lambda: _str("GOOGLE_OAUTH_CLIENT_SECRET"))
    github_oauth_client_id: str = field(default_factory=lambda: _str("GITHUB_OAUTH_CLIENT_ID"))
    github_oauth_client_secret: str = field(default_factory=lambda: _str("GITHUB_OAUTH_CLIENT_SECRET"))
    facebook_oauth_client_id: str = field(default_factory=lambda: _str("FACEBOOK_OAUTH_CLIENT_ID"))
    facebook_oauth_client_secret: str = field(default_factory=lambda: _str("FACEBOOK_OAUTH_CLIENT_SECRET"))

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
    # 2026-04-29: separate origin for *outbound email links*. Today the
    # apex (signal-scout.com → Squarespace 302 → Cloud Run) strips
    # query params on the redirect, so a `?lat=X&lng=Y` deep link in
    # an email lands the user on the bare home page. Until Cloudflare
    # is in front of the apex (PR #318 source ready, no DNS change
    # yet), point email CTAs at the Cloud-Run URL directly. Override
    # via EMAIL_LINK_ORIGIN once the canonical fix is in.
    email_link_origin: str = field(default_factory=lambda: _str(
        "EMAIL_LINK_ORIGIN",
        "https://signal-scout.run.app",
    ))

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
    def app_version_sha(self) -> str:
        """Extract the 7-char git short SHA out of `app_version`.
        '2026.04.24-a3f9c12' → 'a3f9c12'. Returns '' for unparseable
        values (e.g. 'dev') so the footer template can decide whether
        to render the GitHub commit link or just the version label."""
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
        """Lowercased set of admin email addresses, comma-split from
        ADMIN_EMAILS env. Used by /admin/* routes for access control."""
        return {x.strip().lower() for x in self.admin_emails_raw.split(",") if x.strip()}


# Module-level singleton. Imported as `from config import settings`.
settings = Config()


# Audit fix L-NEW-3 (2026-04-27): refuse to boot in production without
# SECRET_KEY. Without it, every Cloud Run instance generates its own
# random key on boot via `secrets.token_hex(32)` (see field default
# above). With session-affinity that *mostly* works — until an
# instance restarts (deploy, scale-down, OOM), at which point every
# itsdangerous-signed cookie fails the signature check and every user
# is silently logged out. Worse: cross-instance requests (browser
# follows a redirect that lands on the other instance) fail too. Fail
# fast at boot so a misconfigured deploy is obvious instead of
# silently breaking sessions for hours.
if settings.is_production and not _str("SECRET_KEY"):
    raise RuntimeError(
        "SECRET_KEY environment variable is required when ENV=PRODUCTION. "
        "Without it every Cloud Run instance generates its own ephemeral "
        "key, invalidating sessions on every restart."
    )
