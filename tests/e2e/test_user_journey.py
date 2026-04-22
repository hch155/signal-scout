"""Golden user journey: home → location → markers → sidebar → marker click.

Headless Chromium against the live Flask server in a thread.
"""
import re
import pytest

pytestmark = [pytest.mark.e2e]


def _wait_for_app_ready(page):
    """Map root + Leaflet initialized + sendLocation defined."""
    page.wait_for_selector("#mapid.leaflet-container", state="attached", timeout=10000)
    page.wait_for_function("typeof sendLocation === 'function'", timeout=5000)


def test_home_renders_map_and_sidebar(page, base_url):
    page.goto(base_url + "/")
    _wait_for_app_ready(page)
    assert page.locator("#sidebar").count() == 1


def test_csp_no_console_violations_on_home(page, base_url):
    """Strict CSP without unsafe-inline must not trigger any blocked-script
    or blocked-style consoles errors on the home page."""
    csp_violations = []
    page.on("console", lambda msg: csp_violations.append(msg.text)
            if "Content Security Policy" in msg.text else None)
    page.goto(base_url + "/")
    _wait_for_app_ready(page)
    page.wait_for_timeout(500)  # let async style/script evals settle
    assert csp_violations == [], f"CSP violations: {csp_violations}"


def test_submit_location_returns_stations_and_renders_sidebar(page, base_url):
    """Programmatic POST + verify markers and sidebar populated."""
    page.goto(base_url + "/")
    _wait_for_app_ready(page)

    # Same JS path the UI uses: read CSRF from meta, call sendLocation.
    with page.expect_response(lambda r: "/submit_location" in r.url) as resp_info:
        page.evaluate("sendLocation(52.2297, 21.0122, 9, null)")
    response = resp_info.value
    assert response.status == 200
    body = response.json()
    assert body["count"] > 0

    page.wait_for_selector(".sidebar-item", timeout=5000)
    assert page.locator(".sidebar-item").count() >= 1
    assert page.locator("#btsCounter").inner_text().strip() != "0"


def test_marker_popup_shows_basestation_id(page, base_url):
    page.goto(base_url + "/")
    _wait_for_app_ready(page)
    page.evaluate("sendLocation(52.2297, 21.0122, 5, null)")
    page.wait_for_selector(".leaflet-marker-icon", timeout=5000)
    page.locator(".leaflet-marker-icon").first.click()
    page.wait_for_selector(".leaflet-popup-content", timeout=3000)
    popup_text = page.locator(".leaflet-popup-content").inner_text()
    assert "Service Provider" in popup_text
    assert "Base Station ID" in popup_text


def test_sidebar_band_chips_get_color_class(page, base_url):
    """Regression for the sidebar bands fix in PR #1: each band lives in its
    own .band-chip span and applyFrequencyColors recolors with text-{color}-600."""
    page.goto(base_url + "/")
    _wait_for_app_ready(page)
    page.evaluate("sendLocation(52.2297, 21.0122, 3, null)")
    page.wait_for_selector(".sidebar-item .band-chip", timeout=5000)
    chip = page.locator(".sidebar-item .band-chip").first
    cls = chip.get_attribute("class") or ""
    assert "band-chip" in cls
    assert re.search(r"text-(green|yellow|orange|red)-600", cls), \
        f"band chip not colored: {cls!r}"
    text = chip.inner_text().strip()
    # Must be an actual band name, NOT the previous regression label like "5G:"
    assert ":" not in text
    assert any(text.startswith(p) for p in ("5G", "LTE", "UMTS", "GSM"))
