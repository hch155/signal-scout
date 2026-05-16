"""Regression coverage for re-audit batch PR B:
- H-NEW-2: lockout counter increments via atomic SQL UPDATE so
  concurrent failed logins don't lose increments.
- M-NEW-2: recovery code consumption is a compare-and-swap; only one
  of two parallel /login/totp requests with the same recovery code
  can succeed.
"""
from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor



# ───────────────────────────────────────────────────────────────────
# H-NEW-2: atomic lockout counter
# ───────────────────────────────────────────────────────────────────

def test_lockout_counter_increments_atomically_under_concurrent_failures(
        client, csrf_token, app):
    """Five concurrent /login posts with a wrong password must result
    in failed_login_attempts >= 5 (not lower due to lost increments)
    AND the user must be locked. The pre-fix Python-side
    read-modify-write would race-lose increments and end up with
    counter=2 or 3 after 5 concurrent attempts."""
    from models import User

    email = f"lock-{secrets.token_hex(3)}@example.com"
    password = "Aa1!aaaaaa"

    # Register the user via the test client first so password_hash is
    # set to something real (otherwise bcrypt comparison short-circuits
    # in a weird way and we wouldn't exercise the lockout path).
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token
    r = client.post("/register", data={
        "_csrf_token": csrf_token, "email": email,
        "password": password, "confirm_password": password,
    })
    assert r.status_code == 200

    # Hammer /login with wrong password concurrently. Five attempts
    # should trip the LOCKOUT_THRESHOLD=5.
    def bad_login() -> int:
        # Each thread needs its own client because Werkzeug test client
        # is not thread-safe across requests sharing one session jar.
        c = app.test_client()
        with c.session_transaction() as s:
            s["_csrf_token"] = csrf_token
        rr = c.post("/login", data={
            "_csrf_token": csrf_token, "email": email,
            "password": "WRONG-PASSWORD",
        }, headers={"Referer": "http://localhost/"})
        return rr.status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: bad_login(), range(5)))

    with app.app_context():
        u = User.query.filter_by(email=email).first()
        assert u is not None
        # The atomic UPDATE guarantees every increment lands; under
        # the racy old code this would frequently be < 5.
        assert u.failed_login_attempts >= 5, (
            f"counter is {u.failed_login_attempts} after 5 concurrent "
            "failed logins — lost increments. H-NEW-2 regressed."
        )
        # And the lockout fired.
        assert u.locked_until is not None


# ───────────────────────────────────────────────────────────────────
# M-NEW-2: recovery code single-use under concurrency
# ───────────────────────────────────────────────────────────────────

def test_recovery_code_compare_and_swap_only_lets_one_session_win(
        authed_client, csrf_token, app):
    """Two parallel /login/totp posts with the same recovery code must
    resolve to ≤ 1 successful login. The pre-fix code did
    hashes.pop(idx) + write-back as a Python-side RMW — both threads
    could pass verification before either commit was durable, both
    promoted to a session. Now: atomic CAS, second commit sees
    rowcount=0 and refuses."""
    from database import db
    from models import User
    import json as _json

    # Set up: enable 2FA on the user with a known recovery code.
    with app.app_context():
        u = User.query.first()
        assert u is not None
        # Bcrypt-hash a single recovery code so we control the value.
        from auth_routes import _bcrypt
        plaintext = "BACKUP-CODE-XYZ-1234"
        h = _bcrypt().generate_password_hash(plaintext).decode('utf-8')
        u.recovery_codes_json = _json.dumps([h])
        u.totp_enabled = True
        # Park a known TOTP secret so the verify() path doesn't crash
        # before falling through to the recovery branch.
        from auth_routes import _wrap_totp_secret
        u.totp_secret_enc = _wrap_totp_secret('JBSWY3DPEHPK3PXP')
        db.session.commit()
        user_id = u.id

    def consume_recovery() -> int:
        c = app.test_client()
        with c.session_transaction() as s:
            s["_csrf_token"] = csrf_token
            s["pending_2fa_user_id"] = user_id
        rr = c.post("/login/totp",
                    data=_json.dumps({"code": plaintext}),
                    content_type="application/json",
                    headers={"X-CSRF-Token": csrf_token,
                             "Referer": "http://localhost/"})
        return rr.status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: consume_recovery(), range(4)))

    successes = sum(1 for code in results if code == 200)
    assert successes <= 1, (
        f"Got {successes} successful logins from one recovery code — "
        "M-NEW-2 CAS regressed; recovery code is no longer single-use."
    )

    # And the code is now consumed (json contains an empty list).
    with app.app_context():
        u = User.query.get(user_id)
        remaining = _json.loads(u.recovery_codes_json or '[]')
        assert remaining == [], (
            f"recovery_codes_json should be empty after consumption, "
            f"got {remaining!r}"
        )
