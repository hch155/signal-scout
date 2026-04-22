"""CSRF helpers — exercised via the Flask app context, not the test client.

These run as unit tests because they don't go through HTTP — they verify the
CSRF helper functions in isolation. No DB needed; we still import the app
because generate_csrf_token / validate_csrf operate on the request session.
"""
import pytest

pytestmark = pytest.mark.unit


def test_generate_csrf_token_idempotent_within_session(app):
    """Calling generate_csrf_token twice in one request must return the same value."""
    from flask import session
    import app as app_module

    with app.test_request_context("/"):
        first = app_module.generate_csrf_token()
        second = app_module.generate_csrf_token()
        assert first == second
        assert "_csrf_token" in session


def test_generate_csrf_token_distinct_across_sessions(app):
    """A fresh session must get a fresh token."""
    import app as app_module

    with app.test_request_context("/"):
        a = app_module.generate_csrf_token()
    with app.test_request_context("/"):
        b = app_module.generate_csrf_token()
    assert a != b


def test_validate_csrf_rejects_missing_token(app):
    import app as app_module

    with app.test_request_context("/somewhere", method="POST"):
        assert app_module.validate_csrf() is False


def test_validate_csrf_rejects_mismatched_token(app):
    import app as app_module
    from flask import session

    with app.test_request_context(
        "/somewhere", method="POST", headers={"X-CSRF-Token": "wrong"}
    ):
        session["_csrf_token"] = "right"
        assert app_module.validate_csrf() is False


def test_validate_csrf_accepts_matching_header(app):
    import app as app_module
    from flask import session

    with app.test_request_context(
        "/somewhere", method="POST", headers={"X-CSRF-Token": "match"}
    ):
        session["_csrf_token"] = "match"
        assert app_module.validate_csrf() is True


def test_validate_csrf_accepts_matching_form_field(app):
    import app as app_module
    from flask import session

    with app.test_request_context(
        "/somewhere", method="POST", data={"_csrf_token": "match"}
    ):
        session["_csrf_token"] = "match"
        assert app_module.validate_csrf() is True
