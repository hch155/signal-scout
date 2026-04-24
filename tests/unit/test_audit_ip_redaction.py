"""GDPR IP-redaction helper — pure-logic unit tests (no DB, no app).

Truncation rule (industry standard, e.g. Plausible / GA IP-anonymisation):
- IPv4: zero the last octet → 192.168.1.42 → 192.168.1.0
- IPv6: keep top 48 bits, zero the rest → 2001:db8:abcd:1234::1 → 2001:db8:abcd::

Edge cases covered: empty input, junk input, X-Forwarded-For chain (we keep
the first hop = client; the rest are infrastructure).
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

# auth_routes is imported as a top-level module from src/, mirroring how the
# rest of the suite reaches into the app package.
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")),
)

from auth_routes import _redact_ip  # noqa: E402


def test_redact_ipv4_drops_last_octet():
    assert _redact_ip("192.168.1.42") == "192.168.1.0"


def test_redact_ipv4_public():
    assert _redact_ip("8.8.8.8") == "8.8.8.0"


def test_redact_ipv6_keeps_top_48_bits():
    assert _redact_ip("2001:db8:abcd:1234:5678::1") == "2001:db8:abcd::"


def test_redact_ipv6_loopback_also_redacted():
    # Loopback gets the same treatment — keeps the helper uniform / no
    # special-case branches the caller has to reason about.
    assert _redact_ip("::1") == "::"


def test_redact_unparseable_returns_empty():
    # Garbage input → empty string. We deliberately don't store junk in the
    # audit row; an empty ip_address column means "we couldn't tell".
    assert _redact_ip("not-an-ip") == ""


def test_redact_empty_returns_empty():
    assert _redact_ip("") == ""


def test_redact_xff_chain_takes_first_hop():
    # X-Forwarded-For is "client, proxy1, proxy2" — the client is the first
    # entry; everything after is our own infra and uninteresting.
    assert _redact_ip("192.168.1.1, 10.0.0.1, 172.16.0.1") == "192.168.1.0"
