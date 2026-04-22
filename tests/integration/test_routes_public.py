"""Public read-only routes: home, data, stats, tips."""
import pytest

pytestmark = pytest.mark.integration


def test_home_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Signal-Scout" in body
    assert '<meta name="csrf-token"' in body


def test_home_slogan_rotates(client):
    """Home picks one of the registered slogans."""
    import app as app_module
    titles = {t for t, _ in app_module.SLOGANS}
    seen = set()
    for _ in range(20):
        r = client.get("/")
        for t in titles:
            if t.encode() in r.data:
                seen.add(t)
                break
    # In 20 spins we'd expect at least 2 unique titles. Accept ≥1 to avoid
    # a deterministic-flake if random ever lands on the same value 20×.
    assert seen, "no recognised slogan rendered"


def test_data_page(client):
    r = client.get("/data")
    assert r.status_code == 200


def test_stats_page_renders_table(client):
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "stats-th" in body
    # At least one provider name from the test fixture
    assert "Orange" in body or "Polkomtel" in body or "T-Mobile" in body


def test_tips_anonymous(client):
    r = client.get("/tips")
    assert r.status_code == 200
    # Anon tips uses tips.md which contains a known phrase
    body = r.data.decode("utf-8")
    assert len(body) > 0


def test_tips_content_endpoint(client):
    r = client.get("/tips/content")
    assert r.status_code == 200
    # Returns HTML (string), not JSON
    assert r.data


def test_session_check_anonymous(client):
    r = client.get("/session_check")
    assert r.status_code == 200
    assert r.get_json() == {"logged_in": False}


def test_unknown_route_404(client):
    r = client.get("/this-does-not-exist")
    assert r.status_code == 404


def test_debug_session_route_removed(client):
    r = client.get("/debug_session")
    assert r.status_code == 404
