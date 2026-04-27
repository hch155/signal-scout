"""Pin the contract that prevents the Sign-in modal regression.

The bug we're guarding against (PR #309): JavaScript that toggles
visibility via classList.remove('hidden') will silently fail if some
earlier code path stamps an inline `element.style.display = 'none'`
on the same element. Inline styles win over class CSS, so the modal
stays invisible even after the class is removed.

These tests run without a real browser — they parse the rendered
HTML + the minified bundle and assert the load-bearing pieces
without paying for Playwright/Chromium boot.
"""
from __future__ import annotations

import os
import re

import pytest


BUNDLE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "static", "dist", "pages", "common.min.js",
))


# ───────────────────────────────────────────────────────────────────
# HTML contract
# ───────────────────────────────────────────────────────────────────

def test_home_page_renders_signin_button_and_modal(client):
    """If either the button or the modal disappears from the template,
    the click handler in initializeModalToggle has nothing to wire up."""
    r = client.get("/", headers={"Referer": "http://localhost/"})
    assert r.status_code == 200
    body = r.data.decode()
    assert 'id="signInBtn"' in body, "Sign in button missing from header"
    assert 'id="authModal"' in body, "Auth modal missing from page"


def test_auth_modal_is_hidden_at_rest_via_class_only(client):
    """The modal must rely on the .hidden Tailwind class for its
    closed-at-rest state, NOT on an inline style. If a future template
    edit adds `style="display:none"` to #authModal, _openAuthModal's
    classList.remove('hidden') will lose to the inline style and the
    modal will silently stay closed (PR #309 regression class)."""
    r = client.get("/", headers={"Referer": "http://localhost/"})
    body = r.data.decode()
    m = re.search(r'<div\s+id="authModal"\s+([^>]*)>', body)
    assert m, "authModal div not found"
    attrs = m.group(1)
    assert "hidden" in attrs, \
        "authModal lost its .hidden class — modal will be open by default"
    assert "display:none" not in attrs.replace(" ", "").lower(), \
        ("authModal has inline style display:none — this defeats "
         "_openAuthModal's class-based show. Use the .hidden class only.")
    assert "display: none" not in attrs.lower(), \
        "Same as above; inline display:none breaks click-to-open."


# ───────────────────────────────────────────────────────────────────
# JS bundle contract
# ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def common_bundle() -> str:
    """The actual minified bundle that ships to browsers. We assert
    against this rather than the source so a build-time regression
    (esbuild ate something, source-vs-build drift) is caught too."""
    assert os.path.exists(BUNDLE_PATH), \
        f"common.min.js not built — run scripts/build.sh ({BUNDLE_PATH})"
    with open(BUNDLE_PATH, encoding="utf-8") as f:
        return f.read()


def test_bundle_does_not_inline_display_authModal(common_bundle):
    """The exact regression from PR #309: checkLoginStateAndUpdateUI
    used to call safelyUpdateDisplay('authModal', 'none'), which set
    inline display:none and pinned the modal closed. If anyone re-
    introduces it (or adds authModal.style.display='none' elsewhere),
    this test fails fast — long before a user notices."""
    # safelyUpdateDisplay('authModal', ...) → setting inline style.
    assert "safelyUpdateDisplay(\"authModal\"" not in common_bundle, \
        ("safelyUpdateDisplay('authModal', ...) re-introduced. This sets "
         "inline display, which breaks click-to-open. Use the .hidden "
         "class instead — see PR #309.")
    # Direct authModal.style.display = '<truthy>' (only `=''` clearing is OK).
    bad = re.findall(
        r"authModal\.style\.display\s*=\s*['\"]([^'\"]+)['\"]",
        common_bundle,
    )
    assert not bad, (
        f"authModal.style.display assigned to {bad!r}. The only allowed "
        "value is the empty string (used in _openAuthModal to clear any "
        "stale inline style). Anything else pins the modal — PR #309."
    )


def test_bundle_open_handlers_clear_inline_display(common_bundle):
    """Defensive contract from PR #309 fix: _openAuthModal sets
    m.style.display = '' before removing the .hidden class, so even if
    a future code path stamps an inline style on the modal, opening it
    still works. Pin that line so it doesn't get refactored away."""
    # Look for any 'style.display=""' (post-minify) — esbuild may emit
    # either '""' or "''" depending on quotes choice. Accept both.
    has_clear = (
        'style.display=""' in common_bundle.replace(" ", "")
        or "style.display=''" in common_bundle.replace(" ", "")
    )
    assert has_clear, (
        "_openAuthModal no longer clears element.style.display before "
        "showing the modal. This is the defense-in-depth from PR #309 — "
        "without it, a stale inline style anywhere in the codebase "
        "silently breaks click-to-open."
    )


# ───────────────────────────────────────────────────────────────────
# Page-load contract
# ───────────────────────────────────────────────────────────────────

def test_session_check_returns_logged_in_false_for_anon(client):
    """conditionalCheckLoginState in common.js calls /session_check on
    every page load (PR #303). If it stops returning a JSON body with
    a `logged_in` field, the header state machine breaks: the OAuth
    login UX from PR #303 silently regresses to the pre-303 bug
    (header keeps showing 'Sign in' after Google OAuth)."""
    r = client.get("/session_check")
    assert r.status_code == 200
    body = r.get_json()
    assert "logged_in" in body, \
        "/session_check stopped returning logged_in field"
    assert body["logged_in"] is False, \
        "fresh client should be anon"


def test_session_check_returns_logged_in_true_after_login(authed_client):
    r = authed_client.get("/session_check")
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("logged_in") is True
