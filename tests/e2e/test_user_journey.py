"""Golden user journey: home → location → markers → sidebar → marker click.

Headless Chromium against the live Flask server in a thread.
"""
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


def test_sidebar_bands_render_as_neutral_text(page, base_url):
    """Sidebar bands are de-vibed: band values render as plain neutral text
    (no per-band color chips). The bold group labels (5G:/LTE:/3G:/GSM:) stay,
    the signal tier is carried by the .signal-bar glyph only."""
    page.goto(base_url + "/")
    _wait_for_app_ready(page)
    page.evaluate("sendLocation(52.2297, 21.0122, 3, null)")
    page.wait_for_selector(".sidebar-item", timeout=5000)
    item = page.locator(".sidebar-item").first

    # No more colored band chips anywhere in the card.
    assert item.locator(".band-chip").count() == 0

    # The bands paragraph still lists real band names behind a bold label.
    bands_p = item.locator("p", has_text="Bands:").first
    text = bands_p.inner_text()
    assert any(p in text for p in ("5G", "LTE", "UMTS", "GSM"))

    # Signal tier indicator (the restrained bar glyph) is present in the header.
    assert item.locator(".signal-label .signal-bar").count() >= 1
