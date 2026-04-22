"""Register → login → logout in a real browser."""
import secrets
import pytest

pytestmark = [pytest.mark.e2e]


def test_register_login_logout_cycle(page, base_url):
    email = f"e2e-{secrets.token_hex(4)}@example.com"
    password = "Aa1!aaaaaa"

    page.goto(base_url + "/")

    # Open Sign Up modal
    page.locator("#registerBtn").click()
    page.wait_for_selector("#registrationModal", state="visible")
    page.locator("#registrationModal #email").fill(email)
    page.locator("#registrationPassword").fill(password)
    page.locator("#confirmRegistrationPassword").fill(password)

    with page.expect_response(lambda r: "/register" in r.url) as resp_info:
        page.locator("#registrationModal button[type=submit]").click()
    assert resp_info.value.status == 200

    # Open Sign In modal
    page.wait_for_timeout(300)  # let modal close + toast show
    page.locator("#signInBtn").click()
    page.wait_for_selector("#signInModal", state="visible")
    page.locator("#signInModal #email").fill(email)
    page.locator("#loginPassword").fill(password)

    with page.expect_response(lambda r: "/login" in r.url) as resp_info:
        page.locator("#signInModal button[type=submit]").click()
    assert resp_info.value.status == 200

    # Logout button becomes visible after successful login
    page.wait_for_selector("#logoutButton:visible", timeout=3000)

    # Click logout (our PR #1 wired this via addEventListener, not inline onclick)
    with page.expect_response(lambda r: "/logout" in r.url) as resp_info:
        page.locator("#logoutButton").click()
    assert resp_info.value.status == 200

    # logoutButton hidden again
    page.wait_for_selector("#logoutButton", state="hidden", timeout=3000)
