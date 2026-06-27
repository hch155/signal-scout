"""Transactional email path for verification + security mail.

`send_transactional` mirrors `emails._send` but does not honour the
recipient's `email_alerts_enabled` preference or the `EmailSuppression`
list: a user must always be able to verify their address, reset a
password, and learn about security-relevant account changes. From is
still built from settings (via the active backend) and
`email_send_total` is still recorded. The marketing / coverage-alert
path in `emails._send` is left untouched.
"""

from __future__ import annotations

import logging

from config import settings


logger = logging.getLogger(__name__)


def send_transactional(user, subject: str, template: str, **ctx) -> bool:
    import emails

    def _bump(outcome: str):
        try:
            from observability import email_send_total
            email_send_total.labels(template=template, outcome=outcome).inc()
        except Exception:
            pass

    if user is None or not getattr(user, 'email', None):
        _bump('no_user')
        return False

    ctx.setdefault('user', user)
    ctx.setdefault('greeting_name', emails._greeting_name(user))
    try:
        ctx.setdefault('unsubscribe_url', emails.unsubscribe_url(user))
    except Exception:
        ctx.setdefault('unsubscribe_url', '')
    try:
        html, text = emails._render(template, **ctx)
    except Exception:
        logger.exception("[email] transactional render failed: %s", template)
        _bump('render_failed')
        return False

    extra_headers: dict = {}
    unsub = ctx.get('unsubscribe_url') or ''
    if unsub:
        extra_headers['List-Unsubscribe'] = (
            f"<mailto:{settings.email_from}?subject=unsubscribe>, <{unsub}>"
        )
        extra_headers['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'

    ok = emails.get_backend().send(emails.EmailMessage(
        to=user.email, subject=subject, html_body=html, text_body=text,
        extra_headers=extra_headers,
    ))
    _bump('sent' if ok else 'send_failed')
    return ok


def send_welcome(user, verification_url: str) -> bool:
    return send_transactional(
        user,
        subject="Welcome to Signal-Scout — please verify your email",
        template='welcome',
        verification_url=verification_url,
    )


def send_password_changed(user) -> bool:
    return send_transactional(
        user,
        subject="Your Signal-Scout password was changed",
        template='password_changed',
    )


def send_password_reset(user, reset_url: str) -> bool:
    return send_transactional(
        user,
        subject="Reset your Signal-Scout password",
        template='password_reset',
        reset_url=reset_url,
    )


def send_2fa_enabled(user) -> bool:
    return send_transactional(
        user,
        subject="Two-factor authentication enabled on your Signal-Scout account",
        template='2fa_enabled',
    )


def send_2fa_disabled(user) -> bool:
    return send_transactional(
        user,
        subject="Two-factor authentication disabled on your Signal-Scout account",
        template='2fa_disabled',
    )


def send_recovery_code_used(user) -> bool:
    return send_transactional(
        user,
        subject="A Signal-Scout 2FA recovery code was just used",
        template='recovery_used',
    )
