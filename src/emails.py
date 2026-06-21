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

from flask import render_template

from config import settings


logger = logging.getLogger(__name__)


def _redact_email(addr: str) -> str:
    """Audit 2026-06-10: full addresses don't belong in app logs —
    /privacy describes app-side records as the truncated-IP audit log
    only. `h***@example.com` keeps logs greppable per-domain and
    distinguishable without storing the actual address."""
    local, _, domain = (addr or '').partition('@')
    if not domain:
        return '***'
    return f"{local[:1]}***@{domain}"


@dataclass
class EmailMessage:
    to: str
    subject: str
    html_body: str
    text_body: str
    extra_headers: Optional[dict] = None


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
                    _redact_email(msg.to), msg.subject, len(msg.html_body), len(msg.text_body))
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
            for hk, hv in (msg.extra_headers or {}).items():
                mime[hk] = hv
            mime.attach(MIMEText(msg.text_body, 'plain', 'utf-8'))
            mime.attach(MIMEText(msg.html_body, 'html', 'utf-8'))

            with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.sendmail(settings.email_from, [msg.to], mime.as_string())
            logger.info("[email:smtp] sent to=%s subject=%r", _redact_email(msg.to), msg.subject)
            return True
        except Exception:
            logger.exception("[email:smtp] failed to=%s subject=%r",
                             _redact_email(msg.to), msg.subject)
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
                         _redact_email(msg.to))
            return False
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, From, To, Subject, PlainTextContent, HtmlContent

            mail = Mail(
                from_email=From(settings.email_from, settings.email_from_name),
                to_emails=To(msg.to),
                subject=Subject(msg.subject),
                plain_text_content=PlainTextContent(msg.text_body),
                html_content=HtmlContent(msg.html_body),
            )
            for hk, hv in (msg.extra_headers or {}).items():
                from sendgrid.helpers.mail import Header
                mail.add_header(Header(hk, hv))
            sg = SendGridAPIClient(self.api_key)
            response = sg.send(mail)
            ok = 200 <= response.status_code < 300
            if ok:
                logger.info("[email:sendgrid] sent to=%s subject=%r status=%d",
                            _redact_email(msg.to), msg.subject, response.status_code)
            else:
                logger.error("[email:sendgrid] non-2xx to=%s status=%d body=%s",
                             _redact_email(msg.to), response.status_code,
                             (getattr(response, 'body', b'') or b'')[:500])
            return ok
        except Exception:
            logger.exception("[email:sendgrid] exception to=%s subject=%r",
                             _redact_email(msg.to), msg.subject)
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
        import re
        text = re.sub(r'<[^>]+>', '', html)
    return html, text


def unsubscribe_url(user) -> str:
    """Build a signed `/unsubscribe/<token>` URL for `user`.

    Token is the user's id signed with `settings.secret_key + salt`,
    so an attacker can't unsubscribe someone else without knowing the
    server secret. The unsubscribe view double-confirms via POST so a
    spec-compliant link prefetcher (Outlook, Gmail's "Show images")
    can't accidentally opt the user out on a GET.
    """
    from itsdangerous import URLSafeSerializer
    from flask import url_for
    serializer = URLSafeSerializer(settings.secret_key, salt='email-unsubscribe')
    token = serializer.dumps(int(user.id))
    return url_for('unsubscribe_email', token=token, _external=True)


def _greeting_name(user) -> str:
    e = (user.email or '').strip()
    if '@' in e:
        return e.split('@', 1)[0]
    return e or 'there'


def _send(user, subject: str, template: str, **ctx) -> bool:
    """Render + send via the active backend. Best-effort by contract.

    PR #48.3 changes:
    - Takes `user` (not bare `to` string) so we can check the
      email_alerts_enabled flag and build the unsubscribe URL.
    - Short-circuits when `user.email_alerts_enabled` is False — no
      email of any kind goes out, returns True (silent skip — caller
      doesn't need to care about user preference).
    - Adds `unsubscribe_url` and `greeting_name` to template context
      so every template can render the footer + greeting consistently.

    2026-04-29: also short-circuits when the recipient address is on
    the local suppression list (hard bounce / spam complaint via the
    SendGrid event webhook). Returns True so callers don't retry —
    the suppression IS the success path for "we should not email
    this address".
    """
    def _bump(outcome: str):
        try:
            from observability import email_send_total
            email_send_total.labels(template=template, outcome=outcome).inc()
        except Exception:
            pass

    if user is None or not getattr(user, 'email', None):
        _bump('no_user')
        return False
    if not getattr(user, 'email_alerts_enabled', True):
        logger.info("[email] skipping %s for user %s (alerts disabled)",
                    template, user.id)
        _bump('alerts_disabled')
        return True
    try:
        from models import EmailSuppression as _ES
        sup = _ES.query.filter_by(email=user.email.lower()).first()
        if sup:
            logger.info("[email] suppressed %s to=%s reason=%s (since %s)",
                        template, _redact_email(user.email), sup.reason, sup.created_at)
            _bump('suppressed')
            return True
    except Exception:
        logger.exception("[email] suppression-check failed (allowing send)")

    ctx.setdefault('user', user)
    ctx.setdefault('greeting_name', _greeting_name(user))
    try:
        ctx.setdefault('unsubscribe_url', unsubscribe_url(user))
    except Exception:
        ctx.setdefault('unsubscribe_url', '')
    try:
        html, text = _render(template, **ctx)
    except Exception:
        logger.exception("[email] template render failed: %s", template)
        _bump('render_failed')
        return False

    extra_headers: dict = {}
    unsub = ctx.get('unsubscribe_url') or ''
    if unsub:
        extra_headers['List-Unsubscribe'] = (
            f"<mailto:{settings.email_from}?subject=unsubscribe>, <{unsub}>"
        )
        extra_headers['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'

    ok = get_backend().send(EmailMessage(
        to=user.email, subject=subject, html_body=html, text_body=text,
        extra_headers=extra_headers,
    ))
    _bump('sent' if ok else 'send_failed')
    return ok


# ── Public per-event helpers ──────────────────────────────────────────────

def send_welcome(user, verification_url: str) -> bool:
    return _send(
        user,
        subject="Welcome to Signal-Scout — please verify your email",
        template='welcome',
        verification_url=verification_url,
    )


def send_password_changed(user) -> bool:
    return _send(
        user,
        subject="Your Signal-Scout password was changed",
        template='password_changed',
    )


def send_password_reset(user, reset_url: str) -> bool:
    return _send(
        user,
        subject="Reset your Signal-Scout password",
        template='password_reset',
        reset_url=reset_url,
    )


def send_2fa_enabled(user) -> bool:
    return _send(
        user,
        subject="Two-factor authentication enabled on your Signal-Scout account",
        template='2fa_enabled',
    )


def send_2fa_disabled(user) -> bool:
    return _send(
        user,
        subject="Two-factor authentication disabled on your Signal-Scout account",
        template='2fa_disabled',
    )


def send_recovery_code_used(user) -> bool:
    return _send(
        user,
        subject="A Signal-Scout 2FA recovery code was just used",
        template='recovery_used',
    )


def _coverage_alert_subject(location, gained, lost, distance_changes) -> tuple:
    """Build an action-led subject + a one-line preheader from the diff.

    Industry pattern: put the *headline fact* in the subject so users
    decide to open without expanding the body. Returns (subject, preheader).
    """
    parts = []
    if gained:
        first = gained[0]['band'] if isinstance(gained[0], dict) else gained[0]
        parts.append(f"+{first}" if len(gained) == 1 else f"+{first} (and {len(gained) - 1} more)")
    if lost:
        first = lost[0]['band'] if isinstance(lost[0], dict) else lost[0]
        parts.append(f"−{first}" if len(lost) == 1 else f"−{first} (and {len(lost) - 1} more)")
    if not parts and distance_changes:
        c = distance_changes[0]
        parts.append(f"{c['band']} { '%+.1f' % c['delta_km']} km")

    headline = ' / '.join(parts) if parts else 'coverage updated'
    subject = f'{location.name}: {headline}'

    pre_bits = []
    if gained:
        pre_bits.append(f"gained {len(gained)}")
    if lost:
        pre_bits.append(f"lost {len(lost)}")
    if distance_changes:
        pre_bits.append(f"{len(distance_changes)} distance change{'s' if len(distance_changes) > 1 else ''}")
    preheader = (' · '.join(pre_bits) + f" at {location.name}").strip()
    return subject, preheader


def send_coverage_alert(user, location, gained, lost, distance_changes,
                         before_recorded_at: Optional[str] = None,
                         current_nearest: Optional[dict] = None) -> bool:
    """Sent by the coverage-alert sweep after a UKE refresh when a
    SavedLocation's coverage materially changed.

    `gained` / `lost` are lists of dicts (band + bts_id + city + provider).
    `distance_changes` is a list of dicts (band, before_km, after_km,
    delta_km, before_bts, after_bts).
    `before_recorded_at` is the ISO timestamp of the snapshot we
    diffed against — rendered in the body as the comparison anchor
    ("compared to UKE data from 2026-03-25"). Optional; falls back to
    "the previous refresh" in the template.
    Caller is expected to only fire this when at least one input is
    non-empty."""
    subject, preheader = _coverage_alert_subject(
        location, gained, lost, distance_changes,
    )
    return _send(
        user,
        subject=subject,
        template='coverage_alert',
        location=location,
        gained=gained,
        lost=lost,
        distance_changes=distance_changes,
        preheader=preheader,
        before_recorded_at=before_recorded_at,
        current_nearest=current_nearest,
    )
