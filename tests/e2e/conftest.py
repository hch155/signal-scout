"""Playwright fixtures for end-to-end tests.

We start the Flask app in a background thread (Werkzeug's dev server) on a
random port, then point Playwright at it. Same isolated DB fixtures from the
top-level conftest.py are reused — no separate test data.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def app_server(app):
    """Yield (host, port) of a Flask dev server running in a daemon thread.

    Named app_server (not live_server) to avoid collision with pytest-flask's
    live_server fixture, which has its own autouse hook that expects a
    different return shape."""
    port = _free_port()
    host = "127.0.0.1"

    def run():
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    # Wait for the port to accept connections (up to ~3s)
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=0.2)
            s.close()
            break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"Flask dev server did not come up on {host}:{port}")

    yield host, port


@pytest.fixture(scope="session")
def base_url(app_server) -> str:
    host, port = app_server
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Override pytest-playwright defaults — viewport that fits the map UI."""
    return {**browser_context_args, "viewport": {"width": 1280, "height": 800}}
