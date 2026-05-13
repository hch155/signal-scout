"""GDPR IP-redaction helper — pure-logic unit tests (no DB, no app).

Truncation rule (industry standard, e.g. Plausible / GA IP-anonymisation):
- IPv4: zero the last octet → 192.168.1.42 → 192.168.1.0
- IPv6: keep top 48 bits, zero the rest → 2001:db8:abcd:1234::1 → 2001:db8:abcd::

Edge cases covered: empty input, junk input, X-Forwarded-For chain (we keep
the first hop = client; the rest are infrastructure).

Import note: `auth_routes` transitively imports `app`, which reads
STATIONS_DB_PATH at import time. tests/conftest.py sets that env var
inside the session-scoped `app` fixture — i.e. at *runtime*, not at
collection. If we imported `auth_routes` at module level here, pytest
collection would import `app` before the env was set, caching it
against the wrong DB and breaking unrelated integration tests
(test_api_v1_find_station_works hits T1000 fixture-only rows).
Lazy-import inside each test keeps unit-test collection side-effect-free.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit


def _import_redact_ip():
    src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    from auth_routes import _redact_ip
    return _redact_ip


def test_redact_ipv4_drops_last_octet():
    _redact_ip = _import_redact_ip()
    assert _redact_ip("192.168.1.42") == "192.168.1.0"


def test_redact_ipv4_public():
    _redact_ip = _import_redact_ip()
    assert _redact_ip("8.8.8.8") == "8.8.8.0"


def test_redact_ipv6_keeps_top_48_bits():
    _redact_ip = _import_redact_ip()
    assert _redact_ip("2001:db8:abcd:1234:5678::1") == "2001:db8:abcd::"


def test_redact_ipv6_loopback_also_redacted():
    # Loopback gets the same treatment — keeps the helper uniform / no
    # special-case branches the caller has to reason about.
    _redact_ip = _import_redact_ip()
    assert _redact_ip("::1") == "::"


def test_redact_unparseable_returns_empty():
    # Garbage input → empty string. We deliberately don't store junk in the
    # audit row; an empty ip_address column means "we couldn't tell".
    _redact_ip = _import_redact_ip()
    assert _redact_ip("not-an-ip") == ""


def test_redact_empty_returns_empty():
    _redact_ip = _import_redact_ip()
    assert _redact_ip("") == ""


def test_redact_xff_chain_takes_first_hop():
    # X-Forwarded-For is "client, proxy1, proxy2" — the client is the first
    # entry; everything after is our own infra and uninteresting.
    _redact_ip = _import_redact_ip()
    assert _redact_ip("192.168.1.1, 10.0.0.1, 172.16.0.1") == "192.168.1.0"
