"""Visual screenshots for PR #46 (UI polish).

Captures the home, /data, /tips, and /account pages at 375px (iPhone SE)
and 768px (iPad mid) viewports so the PR reviewer can eyeball mobile-still-
works alongside the desktop polish. Saved under tests/results/pr46-screens/
so the pre-existing repo .gitignore for tests/results keeps them out of git;
the PR body links to GitHub-hosted copies uploaded separately.

This is a single test using the shared `app_server` / `browser_context_args`
fixtures from tests/e2e/conftest.py — no new fixtures, no Flask threading
glue. Run with:

    pytest tests/e2e/test_screenshots_pr46.py -q
"""
from __future__ import annotations

import os
import secrets
import pytest

pytestmark = [pytest.mark.e2e]


# (label, path, requires_login)
PAGES = [
    ("home", "/", False),
    ("data", "/data", False),
    ("tips", "/tips", False),
    ("account", "/account", True),
]

# (label, width, height)
VIEWPORTS = [
    ("375", 375, 812),  # iPhone SE / 8 / mini
    ("768", 768, 1024),  # iPad portrait
]


def _register_and_login(page, base_url, csrf_token="test-csrf-token"):
    """Register + log in a throwaway user via /register then /login.

    Mirrors tests/conftest.py::authed_client but goes through the browser
    so the page has the live session cookie.
    """
    email = f"shot-{secrets.token_hex(4)}@example.com"
    password = "Aa1!aaaaaa"

    # Need a CSRF token in the session — easiest is to land a page first
    # so flask_session writes the cookie, then POST.
    page.goto(base_url + "/")
    page.wait_for_load_state("networkidle")

    # Read the CSRF token the server wrote for this session via the meta tag.
    meta_csrf = page.locator('meta[name="csrf-token"]').get_attribute("content")

    page.request.post(
        base_url + "/register",
        form={
            "_csrf_token": meta_csrf,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )
    page.request.post(
        base_url + "/login",
        form={"_csrf_token": meta_csrf, "email": email, "password": password},
    )


def test_capture_pr46_screenshots(browser, base_url):
    """Take 8 screenshots (4 pages × 2 viewports) for the PR body."""
    out_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "results", "pr46-screens")
    )
    os.makedirs(out_dir, exist_ok=True)

    for vp_label, w, h in VIEWPORTS:
        ctx = browser.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page()

        # Pre-register a user so /account renders something real
        _register_and_login(page, base_url)

        for page_label, path, _requires_login in PAGES:
            page.goto(base_url + path)
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                # Map's tile loads can keep network active; a short
                # timeout here is fine for a static screenshot.
                pass
            # Tiny extra settle for fonts / shimmer
            page.wait_for_timeout(400)

            shot_path = os.path.join(out_dir, f"{page_label}-{vp_label}.png")
            page.screenshot(path=shot_path, full_page=True)
            assert os.path.exists(shot_path), f"missing: {shot_path}"

        ctx.close()
