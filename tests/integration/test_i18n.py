"""Polish language toggle: ?lang= switching, session persistence,
<html lang> attribute, fallback behaviour, JS string injection, and
language-aware ETags on cached public pages."""

import pytest

pytestmark = pytest.mark.integration


def test_default_language_is_english(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<html lang="en">' in html
    assert "Statistics" in html
    assert "Statystyki" not in html


def test_lang_pl_switches_and_persists_in_session(client):
    resp = client.get("/?lang=pl")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<html lang="pl">' in html
    assert "Statystyki" in html
    assert "Zaloguj się" in html

    with client.session_transaction() as sess:
        assert sess.get("lang") == "pl"

    # Subsequent request without the param stays Polish.
    resp2 = client.get("/data")
    html2 = resp2.get_data(as_text=True)
    assert '<html lang="pl">' in html2
    assert "Dane sieci" in html2


def test_toggle_back_to_english(client):
    client.get("/?lang=pl")
    resp = client.get("/?lang=en")
    html = resp.get_data(as_text=True)
    assert '<html lang="en">' in html
    assert "Statystyki" not in html
    with client.session_transaction() as sess:
        assert sess.get("lang") == "en"


def test_unknown_lang_value_falls_back_to_english(client):
    resp = client.get("/?lang=de")
    html = resp.get_data(as_text=True)
    assert '<html lang="en">' in html
    with client.session_transaction() as sess:
        assert sess.get("lang") is None


def test_unknown_lang_does_not_clobber_existing_choice(client):
    client.get("/?lang=pl")
    resp = client.get("/?lang=xx")
    html = resp.get_data(as_text=True)
    assert '<html lang="pl">' in html


def test_js_i18n_injection_smoke(client):
    resp = client.get("/?lang=pl")
    html = resp.get_data(as_text=True)
    assert 'id="ss-i18n"' in html
    assert '"lang": "pl"' in html
    assert "Zastosuj filtry" in html  # 'Apply Filters' in the JS string map

    resp_en = client.get("/?lang=en")
    html_en = resp_en.get_data(as_text=True)
    assert 'id="ss-i18n"' in html_en
    assert '"lang": "en"' in html_en
    assert "Zastosuj filtry" not in html_en


def test_public_page_etag_varies_by_language(client):
    etag_en = client.get("/data").headers.get("ETag")
    client.get("/?lang=pl")
    etag_pl = client.get("/data").headers.get("ETag")
    assert etag_en and etag_pl
    assert etag_en != etag_pl


def test_cached_public_pages_vary_on_cookie(client):
    resp = client.get("/data")
    assert resp.status_code == 200
    assert "Cookie" in (resp.headers.get("Vary") or "")
