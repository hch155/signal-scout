"""
Test fixtures.

Design choices:
- The Flask app reads stations.db / users.db from src/instance/. Tests must
  run with isolated copies so they never mutate prod data and stay
  deterministic regardless of which row counts the prod DB happens to have.
- We accomplish isolation by pointing app.config['SQLALCHEMY_DATABASE_URI']
  and SQLALCHEMY_BINDS at temp paths *before* the db is queried in any test.
  The app instance is module-scoped and created fresh per test session.
- Each test gets its own client + a fresh users-table state. Stations are
  read-only, so we share one stations DB copy across the whole session.
"""

from __future__ import annotations

import os
import shutil
import secrets
import tempfile
from typing import Iterator

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURE_STATIONS_DB = os.path.join(ROOT, "tests", "fixtures", "test_stations.db")

CSRF_TOKEN = "test-csrf-token"


@pytest.fixture(scope="session")
def _session_tmpdir() -> Iterator[str]:
    path = tempfile.mkdtemp(prefix="signal-scout-tests-")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session")
def _stations_db_path(_session_tmpdir: str) -> str:
    """Copy the read-only stations fixture into the session tmpdir."""
    dst = os.path.join(_session_tmpdir, "stations.db")
    shutil.copyfile(FIXTURE_STATIONS_DB, dst)
    return dst


@pytest.fixture(scope="session")
def app(_session_tmpdir, _stations_db_path):
    """Flask app bound to isolated DBs.

    app.py reads STATIONS_DB_PATH / USERS_DB_PATH from the environment at
    module-import time. We set them here *before* importing it so the app
    is configured against the test fixtures from the start.
    """
    users_db = os.path.join(_session_tmpdir, "users.db")
    flask_session_dir = os.path.join(_session_tmpdir, "flask_session")
    os.makedirs(flask_session_dir, exist_ok=True)

    os.environ["SECRET_KEY"] = secrets.token_hex(32)
    os.environ["STATIONS_DB_PATH"] = _stations_db_path
    os.environ["USERS_DB_PATH"] = users_db

    import sys
    sys.path.insert(0, os.path.join(ROOT, "src"))

    import app as app_module  # noqa: E402
    flask_app = app_module.app

    flask_app.config["TESTING"] = True
    flask_app.config["SESSION_COOKIE_SECURE"] = False  # test client over http
    flask_app.config["SESSION_FILE_DIR"] = flask_session_dir

    yield flask_app


def _client_with_default_referer(app):
    """Test client that injects a same-origin Referer header on every call.

    PR #5 added a Referer / Origin gate on GET data endpoints. Real browsers
    set Referer automatically; the test client doesn't. We inject it so
    legacy tests don't need to change. Tests that explicitly want to
    exercise the access gate use the `raw_client` fixture instead.
    """
    c = app.test_client()
    original_open = c.open

    def open_with_referer(*args, **kwargs):
        headers = kwargs.get('headers') or {}
        # Werkzeug accepts both Header objects and lists; normalize to dict.
        if hasattr(headers, 'items'):
            existing = {k.lower(): v for k, v in headers.items()}
        else:
            existing = {k.lower(): v for k, v in headers}
        if 'referer' not in existing:
            if isinstance(headers, dict):
                headers = {**headers, 'Referer': 'http://localhost/'}
            else:
                headers = list(headers) + [('Referer', 'http://localhost/')]
            kwargs['headers'] = headers
        return original_open(*args, **kwargs)

    c.open = open_with_referer
    return c


@pytest.fixture
def client(app):
    """Fresh test client per test (with same-origin Referer auto-injected)."""
    return _client_with_default_referer(app)


@pytest.fixture
def raw_client(app):
    """Test client with NO default headers — used by tests that exercise
    the access-control gate itself (anonymous-without-Referer rejection)."""
    return app.test_client()


@pytest.fixture
def csrf_client(client):
    """Test client with a known CSRF token planted in the session."""
    with client.session_transaction() as sess:
        sess["_csrf_token"] = CSRF_TOKEN
    return client


@pytest.fixture
def csrf_token() -> str:
    return CSRF_TOKEN


@pytest.fixture(autouse=True)
def _isolate_users_table(app):
    """Wipe users (and ApiKey rows) between tests so register/login/key flows
    are independent. ApiKey is FK-bound to User, so delete it first."""
    yield
    from database import db
    from models import User, ApiKey
    with app.app_context():
        db.session.query(ApiKey).delete()
        db.session.query(User).delete()
        db.session.commit()


@pytest.fixture(autouse=True)
def _reset_rate_limiter(app):
    """Rate-limit storage is in-memory and persists across tests by default —
    reset it so a test that POSTs 5 times to /register doesn't trip a later
    test's rate limit budget."""
    yield
    try:
        import app as app_module
        app_module.limiter.reset()
    except Exception:
        pass


@pytest.fixture
def authed_client(client, csrf_token):
    """Client that has registered a known user, logged in, and holds the session."""
    email = f"user-{secrets.token_hex(4)}@example.com"
    password = "Aa1!aaaaaa"

    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token

    reg = client.post(
        "/register",
        data={
            "_csrf_token": csrf_token,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )
    assert reg.status_code == 200, f"register failed: {reg.status_code} {reg.data!r}"

    login = client.post(
        "/login",
        data={"_csrf_token": csrf_token, "email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.status_code} {login.data!r}"

    # session was rotated by login → re-plant CSRF token for any further POSTs
    with client.session_transaction() as sess:
        sess["_csrf_token"] = csrf_token

    return client
