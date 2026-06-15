"""The /build-log page: served from src/content/build-log.md, linked in the footer."""
import pytest

pytestmark = pytest.mark.integration


def test_build_log_page_renders(client):
    r = client.get("/build-log")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Build log" in body
    # Known phrases from the build-log content.
    assert "Performance arc" in body
    assert "Cloud Run" in body


def test_footer_links_to_build_log(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'href="/build-log"' in body
