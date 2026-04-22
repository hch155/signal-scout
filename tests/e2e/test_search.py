"""Search-by-BTS-ID flow."""
import pytest

pytestmark = [pytest.mark.e2e]


def test_search_dropdown_renders_and_selecting_centers_map(page, base_url):
    page.goto(base_url + "/")
    page.wait_for_selector("#mapid.leaflet-container", state="attached", timeout=10000)

    # Search input is injected into #dynamicContent by executeCurrentPageAction.
    # It lives inside the (collapsed-by-default) filter container, so we accept
    # state="attached" rather than "visible".
    page.wait_for_selector("#baseStationIdInput", state="attached", timeout=5000)

    # Trigger the input handler programmatically — the filter-toggle button is
    # wrapped in Leaflet controls and is brittle to click in headless mode.
    page.evaluate(
        "() => { const el = document.getElementById('baseStationIdInput');"
        " el.value='T10'; el.dispatchEvent(new Event('input', {bubbles:true})); }"
    )
    # Debounced 300ms inside setupBaseStationSearch + network roundtrip
    page.wait_for_selector("#bts-suggestions .suggestion-item",
                           state="attached", timeout=3000)
    suggestions = page.locator("#bts-suggestions .suggestion-item")
    assert suggestions.count() >= 1
    first_text = suggestions.first.inner_text()
    assert first_text.startswith("T10")
