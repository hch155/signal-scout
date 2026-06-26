import pytest

pytestmark = pytest.mark.integration

GET_URL = "/api/v1/coverage_card"

REAL_5G_PHRASE = "Prawdziwe 5G (3,5 GHz)"
DISCLAIMER_FRAGMENT = "Szacowane na podstawie lokalizacji nadajników UKE"


def test_known_address_renders_html_card(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/html")

    body = r.get_data(as_text=True)
    assert "Bardzo dobry" in body
    assert REAL_5G_PHRASE in body
    assert DISCLAIMER_FRAGMENT in body

    import app as app_module
    data_date = app_module.get_data_date(app_module.stations_db_path)
    assert data_date
    assert f"Dane UKE: {data_date}" in body


def test_known_address_is_cookie_free(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    assert "public" in r.headers.get("Cache-Control", "")
    assert "Set-Cookie" not in r.headers


def test_no_match_returns_404_html(client):
    r = client.get(GET_URL, query_string={"q": "Qwerty Asdfgh"})
    assert r.status_code == 404
    assert r.headers["Content-Type"].startswith("text/html")
    assert "Nie znaleziono adresu" in r.get_data(as_text=True)


def test_html_special_chars_in_address_are_escaped(client, monkeypatch):
    payload = "<script>alert('xss')</script>"
    monkeypatch.setattr(
        "app.search_addresses",
        lambda *a, **k: [{"display": payload, "lat": 52.2297, "lng": 21.0122}],
    )
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert payload not in body
    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body
