"""HTTP security header regression suite — every PR #1 hardening.

Runs against every public route so we catch a regression that only sets
headers on the home page (which has bitten Flask apps before).
"""
import pytest

pytestmark = pytest.mark.integration

ROUTES = ["/", "/data", "/stats", "/tips", "/session_check"]

REQUIRED_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


@pytest.mark.parametrize("route", ROUTES)
def test_required_headers_on_every_route(client, route):
    r = client.get(route)
    for name, value in REQUIRED_HEADERS.items():
        assert r.headers.get(name) == value, f"{route} missing {name}"
    for name in ["Strict-Transport-Security", "Content-Security-Policy",
                 "Permissions-Policy"]:
        assert name in r.headers, f"{route} missing {name}"


def test_csp_script_src_strict(client):
    """script-src must NOT contain unsafe-inline. The whole point of CSP is
    blocking inline scripts; relaxing this is a regression."""
    r = client.get("/")
    csp = r.headers["Content-Security-Policy"]
    script_src = csp.split("script-src")[1].split(";")[0]
    assert "'unsafe-inline'" not in script_src
    assert "'unsafe-eval'" not in script_src
    assert "'self'" in script_src


def test_csp_object_src_none(client):
    r = client.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "object-src 'none'" in csp


def test_csp_frame_ancestors_none(client):
    """Defense-in-depth alongside X-Frame-Options."""
    r = client.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp


def test_hsts_long_lived(client):
    r = client.get("/")
    sts = r.headers["Strict-Transport-Security"]
    assert "max-age=31536000" in sts
    assert "includeSubDomains" in sts


def test_permissions_policy_locks_down_dangerous_apis(client):
    r = client.get("/")
    pp = r.headers["Permissions-Policy"]
    assert "camera=()" in pp
    assert "microphone=()" in pp
    assert "payment=()" in pp


def test_csrf_meta_tag_renders_on_home(client):
    r = client.get("/")
    body = r.data.decode("utf-8")
    assert '<meta name="csrf-token" content="' in body
    # Token must be 64 hex chars (secrets.token_hex(32))
    import re
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', body)
    assert m and len(m.group(1)) == 64
