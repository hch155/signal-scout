"""Regression coverage for re-audit batch PR E:
- M-NEW-7: audit_event hash chain. Each row carries prev_hash +
  row_hash; tampering with any field on a stored row breaks the
  row's own hash, deleting a middle row breaks the next row's
  prev_hash linkage. Verifier walks the chain and reports broken IDs.
"""
from __future__ import annotations

import json as _json



def _emit_event(app, user_id: int, event_type: str, meta: dict | None = None):
    """Emit an audit event in a real request context (so _audit() picks
    up the request headers it expects)."""
    from auth_routes import _audit
    from database import db
    with app.test_request_context(headers={"X-Forwarded-For": "1.2.3.4",
                                            "User-Agent": "pytest"}):
        _audit(event_type, user_id, meta)
        db.session.commit()


def _verify(user_id: int):
    from auth_routes import verify_audit_chain_for_user
    return verify_audit_chain_for_user(user_id)


def test_audit_chain_valid_for_freshly_emitted_events(authed_client, app):
    """Three sequential _audit() calls produce a valid chain."""
    from models import User
    with app.app_context():
        u = User.query.first()
        user_id = u.id

    for ev in ['probe.one', 'probe.two', 'probe.three']:
        with app.app_context():
            _emit_event(app, user_id, ev)

    with app.app_context():
        ok, broken = _verify(user_id)
        assert ok, f"chain reports broken events: {broken}"


def test_audit_chain_detects_modified_row(authed_client, app):
    """If anyone overwrites an event's meta_json (or any other hashed
    field) without recomputing row_hash, the verifier flags the row."""
    from database import db
    from models import User, AuditEvent
    with app.app_context():
        u = User.query.first()
        user_id = u.id

    for ev in ['login.success', 'profile.updated', 'login.fail']:
        with app.app_context():
            _emit_event(app, user_id, ev, {'foo': 'bar'})

    with app.app_context():
        # The authed_client fixture also emits a login.success event
        # during its setup, so we tamper with one of OUR emitted rows
        # (the middle of the three we just added) to keep the test
        # focused on the contract.
        rows = (AuditEvent.query.filter_by(user_id=user_id)
                .order_by(AuditEvent.created_at, AuditEvent.id).all())
        # Pick the second-from-last row — guaranteed to be one of our
        # three probes regardless of how many fixture-side events
        # preceded them.
        target = rows[-2]
        target.meta_json = _json.dumps({'foo': 'TAMPERED'})
        db.session.commit()

        ok, broken = _verify(user_id)
        assert not ok
        assert target.id in broken


def test_audit_chain_detects_deleted_middle_row(authed_client, app):
    """Deleting a row leaves the next row's prev_hash pointing at a
    now-missing predecessor — chain is broken at that joint."""
    from database import db
    from models import User, AuditEvent
    with app.app_context():
        u = User.query.first()
        user_id = u.id

    for ev in ['e1', 'e2', 'e3', 'e4']:
        with app.app_context():
            _emit_event(app, user_id, ev)

    with app.app_context():
        rows = (AuditEvent.query.filter_by(user_id=user_id)
                .order_by(AuditEvent.created_at, AuditEvent.id).all())
        # Drop event #2 (index 1). Now event #3's prev_hash points at
        # the deleted event's row_hash, but the surviving prior event
        # (#1) has a different row_hash — chain breaks at #3.
        deleted_id = rows[1].id
        survivor_id = rows[2].id
        db.session.delete(rows[1])
        db.session.commit()

        ok, broken = _verify(user_id)
        assert not ok
        assert deleted_id not in broken  # deleted = invisible
        assert survivor_id in broken     # but its successor flagged


def test_audit_chain_isolated_per_user(app):
    """Per-user chains: emitting events for user A doesn't break
    user B's chain — important so /account/delete cascade-removing
    one user doesn't surface as a global tamper signal."""
    from database import db
    from models import User
    with app.app_context():
        u1 = User(email='a@example.com', password_hash='!OAUTH-x')
        u2 = User(email='b@example.com', password_hash='!OAUTH-y')
        db.session.add_all([u1, u2])
        db.session.commit()
        a_id, b_id = u1.id, u2.id

    for ev in ['x', 'y']:
        with app.app_context():
            _emit_event(app, a_id, ev)
            _emit_event(app, b_id, ev)

    with app.app_context():
        ok_a, _ = _verify(a_id)
        ok_b, _ = _verify(b_id)
        assert ok_a and ok_b
