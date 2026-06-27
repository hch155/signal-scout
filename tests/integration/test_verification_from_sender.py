"""Transactional sender: verification + security mail bypass the
marketing gate (email_alerts_enabled / EmailSuppression) and send From
hello@signal-scout.com when EMAIL_FROM is configured.

Counterpart to test_emails_and_coverage_alerts.py, which asserts the
*opposite* for the alerts/coverage path (emails._send skips when alerts
are off or the address is suppressed).
"""
from __future__ import annotations

import dataclasses
import smtplib

import pytest

pytestmark = pytest.mark.integration


def test_verification_sent_when_alerts_disabled(app):
    import emails
    import transactional_email
    from models import User
    from database import db

    with app.app_context():
        user = User(email="txn-alerts-off@example.com", password_hash="x",
                    role="user", email_alerts_enabled=False)
        db.session.add(user)
        db.session.commit()

        captured = {}

        class _Spy:
            def send(self_, msg):
                captured["to"] = msg.to
                return True
        emails._BACKEND_CACHE = _Spy()
        try:
            with app.test_request_context("/"):
                ok = transactional_email.send_welcome(
                    user, "https://signal-scout.com/verify-email?token=t")
            assert ok is True
            assert captured["to"] == "txn-alerts-off@example.com"
        finally:
            emails.reset_backend_cache()


def test_security_mail_sent_when_suppressed(app):
    import emails
    import transactional_email
    from models import User, EmailSuppression
    from database import db

    with app.app_context():
        user = User(email="suppressed-txn@example.com", password_hash="x",
                    role="user", email_alerts_enabled=True)
        db.session.add(user)
        db.session.add(EmailSuppression(email="suppressed-txn@example.com",
                                        reason="bounce", details="hard"))
        db.session.commit()

        captured = {}

        class _Spy:
            def send(self_, msg):
                captured["to"] = msg.to
                return True
        emails._BACKEND_CACHE = _Spy()
        try:
            with app.test_request_context("/"):
                ok = transactional_email.send_password_reset(
                    user, "https://signal-scout.com/reset-password?token=t")
            assert ok is True
            assert captured["to"] == "suppressed-txn@example.com"
        finally:
            emails.reset_backend_cache()


def test_from_is_hello_when_email_from_set(app, monkeypatch):
    import emails
    import transactional_email
    from models import User
    from database import db

    new_settings = dataclasses.replace(
        emails.settings,
        email_from="hello@signal-scout.com",
        email_from_name="Signal-Scout",
    )
    monkeypatch.setattr(emails, "settings", new_settings)

    captured = {}

    class _FakeSMTP:
        def __init__(self, host, port, timeout=10):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, username, password):
            pass

        def sendmail(self, from_addr, to_addrs, msg):
            captured["from_addr"] = from_addr
            captured["msg"] = msg
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    with app.app_context():
        user = User(email="txn-verify@example.com", password_hash="x",
                    role="user", email_alerts_enabled=False)
        db.session.add(user)
        db.session.commit()

        emails._BACKEND_CACHE = emails.SmtpBackend()
        try:
            with app.test_request_context("/"):
                ok = transactional_email.send_welcome(
                    user, "https://signal-scout.com/verify-email?token=t")
            assert ok is True
            assert captured["from_addr"] == "hello@signal-scout.com"
            assert "From: Signal-Scout <hello@signal-scout.com>" in captured["msg"]
        finally:
            emails.reset_backend_cache()


def test_transactional_records_sent_metric(app):
    import emails
    import transactional_email
    from observability import email_send_total
    from models import User
    from database import db

    with app.app_context():
        user = User(email="txn-metric@example.com", password_hash="x",
                    role="user", email_alerts_enabled=False)
        db.session.add(user)
        db.session.commit()

        child = email_send_total.labels(template="welcome", outcome="sent")
        before = child._value.get()

        class _Spy:
            def send(self_, msg):
                return True
        emails._BACKEND_CACHE = _Spy()
        try:
            with app.test_request_context("/"):
                assert transactional_email.send_welcome(
                    user, "https://signal-scout.com/verify-email?token=t") is True
        finally:
            emails.reset_backend_cache()

        assert child._value.get() == before + 1
