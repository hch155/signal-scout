"""Coverage-lifting tests for emails.py + coverage_alerts.py.

emails.py is the transactional backend dispatcher. We hit:
- get_backend() picks NoopBackend by default; reset_backend_cache works.
- _send shortcircuits on no user / alerts disabled / suppression list.
- _send full happy path with NoopBackend records 'sent'.
- _coverage_alert_subject builds an action-led headline.
- unsubscribe_url + _greeting_name helpers.

coverage_alerts.py is the sweep that drives those emails. We hit:
- _coverage_to_dict / _diff (gained, lost, distance_changes).
- _process: first-run snapshot path, no-change path, sent path.
- run_coverage_alert_sweep returns the right counts dict shape.

All of this hits the test-fixture DB (no network, no real email).
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration


# ── emails: low-level helpers ────────────────────────────────────────────────


def test_get_backend_returns_noop_by_default(app):
    import emails
    emails.reset_backend_cache()
    backend = emails.get_backend()
    assert backend.__class__.__name__ == "NoopBackend"


def test_noop_backend_send_returns_true():
    from emails import NoopBackend, EmailMessage
    backend = NoopBackend()
    msg = EmailMessage(
        to="a@b.example", subject="hi", html_body="<p>hi</p>",
        text_body="hi", extra_headers={"X-Custom": "1"},
    )
    assert backend.send(msg) is True


def test_greeting_name_strips_local_part():
    from emails import _greeting_name

    class _U:
        email = "foo.bar@example.com"
    assert _greeting_name(_U()) == "foo.bar"

    class _Empty:
        email = ""
    assert _greeting_name(_Empty()) == "there"


def test_unsubscribe_url_signs_user_id(app):
    """Token round-trips back to the user.id via the same serializer."""
    from emails import unsubscribe_url
    from itsdangerous import URLSafeSerializer
    from config import settings

    class _U:
        id = 42
    with app.test_request_context("/"):
        url = unsubscribe_url(_U())
    assert "/unsubscribe/" in url
    token = url.rsplit("/", 1)[1]
    serializer = URLSafeSerializer(settings.secret_key, salt="email-unsubscribe")
    assert int(serializer.loads(token)) == 42


def test_coverage_alert_subject_with_gained_band():
    from emails import _coverage_alert_subject

    class _Loc:
        name = "Mokotów"
    subject, preheader = _coverage_alert_subject(
        _Loc(),
        gained=[{"band": "5G3600"}],
        lost=[],
        distance_changes=[],
    )
    assert "Mokotów" in subject
    assert "5G3600" in subject
    assert subject.startswith("Mokotów:")
    assert "gained 1" in preheader


def test_coverage_alert_subject_with_distance_change_only():
    from emails import _coverage_alert_subject

    class _Loc:
        name = "Wilanów"
    subject, preheader = _coverage_alert_subject(
        _Loc(),
        gained=[],
        lost=[],
        distance_changes=[{"band": "LTE2600", "delta_km": 1.4}],
    )
    assert "Wilanów" in subject
    assert "LTE2600" in subject
    assert "+1.4 km" in subject
    assert "1 distance change" in preheader


# ── emails: _send happy path + short-circuits ───────────────────────────────


def test_send_skips_alerts_disabled_user(app):
    """User exists, alerts off → returns True (silent skip), no backend call."""
    import emails
    from models import User
    from database import db

    with app.app_context():
        user = User(email="alerts-off@example.com",
                    password_hash="x", role="user", email_alerts_enabled=False)
        db.session.add(user)
        db.session.commit()

        sent_to = []

        class _Spy:
            def send(self_, msg):
                sent_to.append(msg.to)
                return True
        emails._BACKEND_CACHE = _Spy()
        try:
            assert emails._send(user, "subj", "welcome") is True
            assert sent_to == []  # never invoked the backend
        finally:
            emails.reset_backend_cache()


def test_send_returns_false_when_no_user(app):
    import emails
    assert emails._send(None, "s", "welcome") is False


def test_send_with_suppressed_email_short_circuits(app):
    import emails
    from models import User, EmailSuppression
    from database import db

    with app.app_context():
        user = User(email="bounce@example.com", password_hash="x", role="user",
                    email_alerts_enabled=True)
        db.session.add(user)
        db.session.add(EmailSuppression(email="bounce@example.com",
                                         reason="bounce", details="hard"))
        db.session.commit()

        sent_to = []

        class _Spy:
            def send(self_, msg):
                sent_to.append(msg.to)
                return True
        emails._BACKEND_CACHE = _Spy()
        try:
            assert emails._send(user, "s", "welcome") is True
            assert sent_to == []
        finally:
            emails.reset_backend_cache()


def test_send_happy_path_renders_and_calls_backend(app):
    """Full path: user enabled, not suppressed, template renders, backend
    receives the message + extra unsubscribe headers."""
    import emails
    from models import User
    from database import db

    with app.app_context():
        user = User(email="welcome@example.com", password_hash="x", role="user",
                    email_alerts_enabled=True)
        db.session.add(user)
        db.session.commit()

        captured = {}

        class _Capture:
            def send(self_, msg):
                captured["to"] = msg.to
                captured["subject"] = msg.subject
                captured["headers"] = dict(msg.extra_headers or {})
                return True
        emails._BACKEND_CACHE = _Capture()
        try:
            with app.test_request_context("/"):
                ok = emails._send(user, "Welcome subj", "welcome",
                                   verification_url="https://example/verify")
            assert ok is True
            assert captured["to"] == "welcome@example.com"
            assert captured["subject"] == "Welcome subj"
            assert "List-Unsubscribe" in captured["headers"]
            assert "List-Unsubscribe-Post" in captured["headers"]
        finally:
            emails.reset_backend_cache()


# ── coverage_alerts: pure helpers ────────────────────────────────────────────


def test_coverage_to_dict_keeps_only_diffable_fields():
    from coverage_alerts import _coverage_to_dict
    cov = {
        "gaps": [
            {
                "band": "LTE2600",
                "nearest_distance_km": 0.42,
                "has_coverage": True,
                "nearest_basestation_id": "T1000",
                "nearest_city": "Warszawa",
                "nearest_service_provider": "Orange Polska S.A.",
                "EXTRA_FIELD_THAT_SHOULDNT_LEAK": "foo",
            }
        ]
    }
    out = _coverage_to_dict(cov)
    assert "recorded_at" in out
    assert len(out["gaps"]) == 1
    g = out["gaps"][0]
    assert g["band"] == "LTE2600"
    assert g["nearest_basestation_id"] == "T1000"
    assert "EXTRA_FIELD_THAT_SHOULDNT_LEAK" not in g


def test_diff_detects_gained_lost_and_distance_changes():
    from coverage_alerts import _diff
    before = {
        "gaps": [
            {"band": "LTE2600", "nearest_distance_km": 0.5, "has_coverage": True,
             "nearest_basestation_id": "B1", "nearest_city": "Wwa",
             "nearest_service_provider": "Orange Polska S.A."},
            {"band": "5G3600", "nearest_distance_km": 0.8, "has_coverage": True,
             "nearest_basestation_id": "B2", "nearest_city": "Wwa",
             "nearest_service_provider": "P4 Sp. z o.o."},
            {"band": "GSM900", "nearest_distance_km": 5.0, "has_coverage": False,
             "nearest_basestation_id": None, "nearest_city": None,
             "nearest_service_provider": None},
        ]
    }
    after = {
        "gaps": [
            {"band": "LTE2600", "nearest_distance_km": 2.5, "has_coverage": True,
             "nearest_basestation_id": "B1B", "nearest_city": "Wwa",
             "nearest_service_provider": "Orange Polska S.A."},
            # 5G3600 gone (lost)
            {"band": "GSM900", "nearest_distance_km": 0.4, "has_coverage": True,
             "nearest_basestation_id": "B3", "nearest_city": "Wwa",
             "nearest_service_provider": "T-Mobile Polska S.A."},
        ]
    }
    gained, lost, distance_changes = _diff(before, after)
    assert [g["band"] for g in gained] == ["GSM900"]
    assert [le["band"] for le in lost] == ["5G3600"]
    # Provider names are short-formed in the row labels.
    assert gained[0]["provider"] == "T-Mobile"
    assert lost[0]["provider"] == "Play"
    # _diff includes any band present in both snapshots whose distance
    # moved more than the threshold — independent of has_coverage flips.
    # LTE2600 (0.5 → 2.5, +2.0 km) qualifies; GSM900 (5.0 → 0.4, −4.6 km)
    # also qualifies. distance_changes is sorted by |delta_km| desc.
    bands_changed = [c["band"] for c in distance_changes]
    assert "LTE2600" in bands_changed
    assert distance_changes[0]["band"] == "GSM900"  # biggest delta first


def test_diff_ignores_sub_threshold_distance_wobble():
    from coverage_alerts import _diff
    before = {"gaps": [{"band": "LTE2100", "nearest_distance_km": 0.5,
                         "has_coverage": True, "nearest_basestation_id": "X",
                         "nearest_city": "Wwa",
                         "nearest_service_provider": ""}]}
    after = {"gaps": [{"band": "LTE2100", "nearest_distance_km": 0.7,
                        "has_coverage": True, "nearest_basestation_id": "X",
                        "nearest_city": "Wwa",
                        "nearest_service_provider": ""}]}
    gained, lost, distance_changes = _diff(before, after)
    assert (gained, lost, distance_changes) == ([], [], [])


# ── coverage_alerts: _process + run_coverage_alert_sweep ─────────────────────


def _make_user_with_location(app, *, alerting=True, last_state=None):
    from models import User, UserLocation
    from database import db
    user = User(email="alert-test@example.com", password_hash="x", role="user",
                email_alerts_enabled=True)
    db.session.add(user)
    db.session.flush()
    loc = UserLocation(
        user_id=user.id,
        name="Test spot",
        lat=52.2297,
        lng=21.0122,
        radius_km=15.0,
        alerting_enabled=alerting,
        last_coverage_state=last_state,
    )
    db.session.add(loc)
    db.session.commit()
    return user, loc


def test_process_first_run_stamps_snapshot_no_email(app, monkeypatch):
    from coverage_alerts import _process
    from database import db

    sent = []

    def _spy(*args, **kwargs):
        sent.append(args)
        return True
    monkeypatch.setattr("coverage_alerts.emails.send_coverage_alert", _spy)

    with app.app_context():
        user, loc = _make_user_with_location(app, alerting=True, last_state=None)
        status = _process(loc, dry_run=False, verbose=False)
        assert status == "first-run"
        # Snapshot now stamped on the row.
        db.session.refresh(loc)
        assert loc.last_coverage_state is not None
        snap = json.loads(loc.last_coverage_state)
        assert "gaps" in snap
        # No email went out on first run.
        assert sent == []


def test_process_no_change_returns_no_change(app, monkeypatch):
    from coverage_alerts import _process, _coverage_to_dict
    from queries import find_coverage_gaps
    from database import db

    sent = []

    def _spy(*args, **kwargs):
        sent.append(args)
        return True
    monkeypatch.setattr("coverage_alerts.emails.send_coverage_alert", _spy)

    with app.app_context():
        # Pre-stamp the row with the CURRENT coverage so the diff is empty.
        cov = _coverage_to_dict(find_coverage_gaps(52.2297, 21.0122))
        user, loc = _make_user_with_location(
            app, alerting=True, last_state=json.dumps(cov, sort_keys=True),
        )
        status = _process(loc, dry_run=False, verbose=False)
        assert status == "no-change"
        assert sent == []


def test_run_coverage_alert_sweep_returns_counts_shape(app, monkeypatch):
    from coverage_alerts import run_coverage_alert_sweep

    monkeypatch.setattr("coverage_alerts.emails.send_coverage_alert",
                         lambda *a, **kw: True)

    with app.app_context():
        _make_user_with_location(app, alerting=True)
        counts = run_coverage_alert_sweep(dry_run=True, verbose=False)
        assert set(counts.keys()) >= {
            "first-run", "no-change", "sent", "send-failed", "skipped",
            "total_processed",
        }
        assert counts["total_processed"] >= 1


def test_run_coverage_alert_sweep_scoped_by_user_id(app, monkeypatch):
    """user_id filter limits the sweep to one user's locations."""
    from coverage_alerts import run_coverage_alert_sweep
    from models import User, UserLocation
    from database import db

    monkeypatch.setattr("coverage_alerts.emails.send_coverage_alert",
                         lambda *a, **kw: True)

    with app.app_context():
        a = User(email="a@example.com", password_hash="x", role="user",
                 email_alerts_enabled=True)
        b = User(email="b@example.com", password_hash="x", role="user",
                 email_alerts_enabled=True)
        db.session.add_all([a, b])
        db.session.flush()
        for u in (a, b):
            db.session.add(UserLocation(
                user_id=u.id, name=f"loc-{u.id}",
                lat=52.2297, lng=21.0122, alerting_enabled=True,
            ))
        db.session.commit()

        only_a = run_coverage_alert_sweep(dry_run=True, user_id=a.id)
        assert only_a["total_processed"] == 1
        all_users = run_coverage_alert_sweep(dry_run=True)
        assert all_users["total_processed"] >= 2
