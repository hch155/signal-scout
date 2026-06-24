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


def test_sidebar_bands_colored_by_distance(page, base_url):
    """Redesign: bands render as chips grouped under a charcoal generation tag
    (5G/LTE/3G/GSM via .gen-tag). KEEPS per-band colouring — it's data: each
    chip is tinted by its own reach at the station distance (a far low-band can
    be 'good' while a high-band at the same spot is 'poor'). Header carries the
    signal bars + tier label; a thin strength meter sits under the header."""
    page.goto(base_url + "/")
    _wait_for_app_ready(page)
    page.evaluate("sendLocation(52.2297, 21.0122, 3, null)")
    page.wait_for_selector(".sidebar-item", timeout=5000)
    item = page.locator(".sidebar-item").first

    # Bands are chips grouped under charcoal generation tags.
    assert item.locator(".bands-block .gen-tag").count() >= 1
    chips = item.locator(".band-chip")
    assert chips.count() >= 1
    # Each chip is per-band colour-coded via inline style (the feature).
    assert item.locator(".band-chip[style*='color']").count() >= 1

    # Signal tier indicator + thin strength meter are present.
    assert item.locator(".signal-label .signal-bar").count() >= 1
    assert item.locator(".strength-meter .strength-meter-fill").count() == 1


_COUNT_RINGS = (
    "(() => { let n = 0; mymap.eachLayer(l => { if (l instanceof L.Circle) n++; }); return n; })()"
)


def test_outside_pl_click_does_not_break_next_inside_click(page, base_url):
    """Outside-PL click then inside-PL click must still draw the 4 coverage
    rings, and rings must not accumulate across clicks."""
    page.goto(base_url + "/")
    _wait_for_app_ready(page)
    page.wait_for_function("typeof countryBoundaries !== 'undefined'", timeout=5000)

    with page.expect_response(lambda r: "/submit_location" in r.url):
        page.evaluate("mymap.fire('click', {latlng: L.latLng(48.8566, 2.3522)})")
    assert page.evaluate(_COUNT_RINGS) == 0

    with page.expect_response(lambda r: "/submit_location" in r.url):
        page.evaluate("mymap.fire('click', {latlng: L.latLng(52.2297, 21.0122)})")
    page.wait_for_selector(".sidebar-item", timeout=5000)
    assert page.evaluate(_COUNT_RINGS) == 4

    with page.expect_response(lambda r: "/stations" in r.url or "/submit_location" in r.url):
        page.evaluate("mymap.fire('click', {latlng: L.latLng(50.0647, 19.9450)})")
    page.wait_for_timeout(600)
    assert page.evaluate(_COUNT_RINGS) == 4


def test_language_toggle_preserves_location(page, base_url):
    """Switching language must keep the clicked spot: the toggle carries
    lat/lng so the deep-link restores the sidebar + rings after the reload."""
    page.goto(base_url + "/")
    _wait_for_app_ready(page)
    page.evaluate("sendLocation(52.2297, 21.0122, 3, null)")
    page.wait_for_selector(".sidebar-item", timeout=5000)
    page.click("#langToggle")
    page.wait_for_selector(".sidebar-item", timeout=6000)
    assert "lang=" in page.url
    assert page.evaluate(_COUNT_RINGS) == 4
