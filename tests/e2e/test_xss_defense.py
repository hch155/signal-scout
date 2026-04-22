"""XSS regression for PR #1.

The test fixture seeds an adversarial row (basestation_id T9999) whose
service_provider, city, and location contain <script>/<img onerror> payloads.
After the XSS-safe rendering refactor, none of those payloads should execute.
"""
import pytest

pytestmark = [pytest.mark.e2e]


def test_malicious_station_payload_does_not_execute(page, base_url):
    # add_init_script must be registered BEFORE goto so the baseline runs in
    # every new document context.
    page.add_init_script("window.__pwned = false;")
    page.goto(base_url + "/")
    page.wait_for_selector("#mapid.leaflet-container", state="attached", timeout=10000)
    page.wait_for_function("typeof sendLocation === 'function'", timeout=5000)

    # Adversarial row sits at (52.2300, 21.0125) inside Warszawa segment
    page.evaluate("sendLocation(52.2300, 21.0125, 10, null)")
    page.wait_for_selector(".sidebar-item", timeout=5000)

    # Trigger a marker popup so popup HTML rendering is exercised too
    page.locator(".leaflet-marker-icon").first.click()
    page.wait_for_timeout(500)

    pwned = page.evaluate("window.__pwned")
    assert pwned is not True, "XSS payload from station data ran in the page"

    # The literal payloads must not survive as live HTML in either popup or sidebar
    sidebar_html = page.locator("#sidebar").inner_html()
    popup_html = (
        page.locator(".leaflet-popup-content").inner_html()
        if page.locator(".leaflet-popup-content").count()
        else ""
    )
    combined = (sidebar_html + popup_html).lower()
    assert "<script>alert(1)</script>" not in combined
    assert "<img src=x onerror=" not in combined
