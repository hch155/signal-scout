"""Transactional email backends (PR #35).

Why a backend abstraction
-------------------------
Three deployment realities:

- **Local dev / CI**: nobody wants real emails leaking to test inboxes —
  use `noop` (logs only) or `smtp` to a local Mailpit on the NUC.
- **Staging**: Mailpit so the dev can inspect rendered emails in a web
  UI before letting real customers see them.
- **Production**: SendGrid Web API — managed deliverability, DKIM/SPF
  signed via the authenticated domain.

Picked at startup from `config.settings.email_backend`. Hooks in
`auth_routes.py` are best-effort: any failure is caught and logged so a
SendGrid outage never blocks `/register` or `/login`.

Templates live in `src/templates/emails/<name>.html` and `.txt`. Both
variants are sent (multipart/alternative) so HTML-blind / text-only
clients still get a readable body.
"""

from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from flask import current_app, render_template

from config import settings


logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    to: str
    subject: str
    html_body: str
    text_body: str


class EmailBackend(ABC):
    @abstractmethod
    def send(self, msg: EmailMessage) -> bool:
        """Return True on success, False on failure. Never raises —
        backends swallow exceptions and log instead so callers stay simple."""


class NoopBackend(EmailBackend):
    """Default — logs at INFO and discards. Used when EMAIL_BACKEND is
    unset or in tests."""
    def send(self, msg: EmailMessage) -> bool:
        logger.info("[email:noop] to=%s subject=%r (body len html=%d text=%d)",
                    msg.to, msg.subject, len(msg.html_body), len(msg.text_body))
        return True


class SmtpBackend(EmailBackend):
    """Plain SMTP — for Mailpit on the NUC during dev/staging.

    Uses STARTTLS only when SMTP_USE_TLS is set (Mailpit doesn't support
    TLS by default; real SMTP relays do). Auth optional — Mailpit accepts
    anonymous by default."""
    def __init__(self):
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.use_tls = settings.smtp_use_tls

    def send(self, msg: EmailMessage) -> bool:
        try:
            mime = MIMEMultipart('alternative')
            mime['From'] = f"{settings.email_from_name} <{settings.email_from}>"
            mime['To'] = msg.to
            mime['Subject'] = msg.subject
            mime.attach(MIMEText(msg.text_body, 'plain', 'utf-8'))
            mime.attach(MIMEText(msg.html_body, 'html', 'utf-8'))

            with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.sendmail(settings.email_from, [msg.to], mime.as_string())
            logger.info("[email:smtp] sent to=%s subject=%r", msg.to, msg.subject)
            return True
        except Exception:
            logger.exception("[email:smtp] failed to=%s subject=%r",
                             msg.to, msg.subject)
            return False


class SendGridBackend(EmailBackend):
    """SendGrid Web API v3 — for production.

    Requires SENDGRID_API_KEY env var. Imports the SDK lazily so the
    module is importable even if sendgrid isn't installed (e.g. in a
    minimal dev env that uses Mailpit only)."""
    def __init__(self):
        self.api_key = settings.sendgrid_api_key
        if not self.api_key:
            logger.warning("[email:sendgrid] SENDGRID_API_KEY not set — "
                           "every send will fail until configured")

    def send(self, msg: EmailMessage) -> bool:
        if not self.api_key:
            logger.error("[email:sendgrid] no API key, refusing to send to=%s",
                         msg.to)
            return False
        try:
            # Lazy import — sendgrid pulls a few transitive deps; not loading
            # them when the backend is something else keeps cold-start fast.
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, From, To, Subject, PlainTextContent, HtmlContent

            mail = Mail(
                from_email=From(settings.email_from, settings.email_from_name),
                to_emails=To(msg.to),
                subject=Subject(msg.subject),
                plain_text_content=PlainTextContent(msg.text_body),
                html_content=HtmlContent(msg.html_body),
            )
            sg = SendGridAPIClient(self.api_key)
            response = sg.send(mail)
            ok = 200 <= response.status_code < 300
            if ok:
                logger.info("[email:sendgrid] sent to=%s subject=%r status=%d",
                            msg.to, msg.subject, response.status_code)
            else:
                logger.error("[email:sendgrid] non-2xx to=%s status=%d body=%s",
                             msg.to, response.status_code,
                             (getattr(response, 'body', b'') or b'')[:500])
            return ok
        except Exception:
            logger.exception("[email:sendgrid] exception to=%s subject=%r",
                             msg.to, msg.subject)
            return False


_BACKEND_CACHE: Optional[EmailBackend] = None


def get_backend() -> EmailBackend:
    """Pick once at first call (cheap), reuse for the process lifetime.
    Reset to None in tests if a fixture monkeypatches the env."""
    global _BACKEND_CACHE
    if _BACKEND_CACHE is not None:
        return _BACKEND_CACHE
    name = (settings.email_backend or 'noop').lower()
    if name == 'sendgrid':
        _BACKEND_CACHE = SendGridBackend()
    elif name == 'smtp':
        _BACKEND_CACHE = SmtpBackend()
    else:
        _BACKEND_CACHE = NoopBackend()
    logger.info("[email] backend=%s", _BACKEND_CACHE.__class__.__name__)
    return _BACKEND_CACHE


def reset_backend_cache() -> None:
    """Test-only: drop the cached backend so the next get_backend() picks
    up env changes."""
    global _BACKEND_CACHE
    _BACKEND_CACHE = None


# ── Render helpers ────────────────────────────────────────────────────────

def _render(template_name: str, **ctx) -> tuple[str, str]:
    """Render `<template>.html` + `<template>.txt` with the same ctx.
    Both must exist; missing .txt → fall back to a stripped HTML body."""
    html = render_template(f'emails/{template_name}.html', **ctx)
    try:
        text = render_template(f'emails/{template_name}.txt', **ctx)
    except Exception:
        # Crude fallback: strip tags. Better than nothing for spam-folder
        # heuristics that look at multipart shape.
        import re
        text = re.sub(r'<[^>]+>', '', html)
    return html, text


def _send(to: str, subject: str, template: str, **ctx) -> bool:
    """Render + send via the active backend. Best-effort by contract."""
    try:
        html, text = _render(template, **ctx)
    except Exception:
        logger.exception("[email] template render failed: %s", template)
        return False
    return get_backend().send(EmailMessage(
        to=to, subject=subject, html_body=html, text_body=text,
    ))


# ── Public per-event helpers ──────────────────────────────────────────────

def send_welcome(user, verification_url: str) -> bool:
    return _send(
        to=user.email,
        subject="Welcome to Signal-Scout — please verify your email",
        template='welcome',
        user=user, verification_url=verification_url,
    )


def send_password_changed(user) -> bool:
    return _send(
        to=user.email,
        subject="Your Signal-Scout password was changed",
        template='password_changed',
        user=user,
    )


def send_2fa_enabled(user) -> bool:
    return _send(
        to=user.email,
        subject="Two-factor authentication enabled on your Signal-Scout account",
        template='2fa_enabled',
        user=user,
    )


def send_2fa_disabled(user) -> bool:
    return _send(
        to=user.email,
        subject="Two-factor authentication disabled on your Signal-Scout account",
        template='2fa_disabled',
        user=user,
    )


def send_recovery_code_used(user) -> bool:
    return _send(
        to=user.email,
        subject="A Signal-Scout 2FA recovery code was just used",
        template='recovery_used',
        user=user,
    )
