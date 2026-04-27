"""Register → login → logout in a real browser.

Updated for PR #48.8 unified auth modal: the header used to expose
two buttons (#registerBtn + #signInBtn). Now there's just #signInBtn,
and the modal has tab buttons #authTabSignin / #authTabRegister to
swap between Sign in and Create account inside the same modal. The
inner panel IDs (#signInModal / #registrationModal) survive PR #48.8
unchanged.
"""
import secrets
import pytest

pytestmark = [pytest.mark.e2e]


def test_register_login_logout_cycle(page, base_url):
    email = f"e2e-{secrets.token_hex(4)}@example.com"
    password = "Aa1!aaaaaa"

    page.goto(base_url + "/")

    # Open the unified auth modal then switch to Create account tab.
    page.locator("#signInBtn").click()
    page.wait_for_selector("#authModal", state="visible")
    page.locator("#authTabRegister").click()
    page.wait_for_selector("#registrationModal", state="visible")
    page.locator("#registrationModal #email").fill(email)
    page.locator("#registrationPassword").fill(password)
    page.locator("#confirmRegistrationPassword").fill(password)

    with page.expect_response(lambda r: "/register" in r.url) as resp_info:
        page.locator("#registrationModal button[type=submit]").click()
    assert resp_info.value.status == 200

    # Re-open modal on Sign in tab.
    page.wait_for_timeout(300)  # let modal close + toast show
    page.locator("#signInBtn").click()
    page.wait_for_selector("#authModal", state="visible")
    # Sign-in panel is the default tab; still click for explicitness in
    # case earlier interactions left register active.
    page.locator("#authTabSignin").click()
    page.wait_for_selector("#signInModal", state="visible")
    # PR #48.8 unified modal: registration email input keeps id="email"
    # for back-compat with existing tests; the sign-in panel uses
    # id="loginEmail" + id="loginPassword" so HTML id-uniqueness holds.
    page.locator("#loginEmail").fill(email)
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
