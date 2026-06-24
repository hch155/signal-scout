"""Address-search geocode endpoint backed by the local FTS5 PRG database."""
import pytest

pytestmark = pytest.mark.integration


def test_geocode_returns_matching_street(client):
    r = client.get("/geocode?q=Łąkowa Białystok")
    assert r.status_code == 200
    results = r.get_json()["results"]
    assert results
    top = results[0]
    assert top["display"] == "Łąkowa, Białystok"
    assert top["lat"] == pytest.approx(53.1395, abs=1e-3)
    assert top["lng"] == pytest.approx(23.1725, abs=1e-3)


def test_geocode_ascii_query_matches_diacritics(client):
    # User types without Polish letters — folding must still match.
    r = client.get("/geocode?q=lakowa bialystok")
    results = r.get_json()["results"]
    assert any(x["display"] == "Łąkowa, Białystok" for x in results)


def test_geocode_short_query_returns_empty(client):
    r = client.get("/geocode?q=ab")
    assert r.status_code == 200
    assert r.get_json()["results"] == []


def test_geocode_no_match_returns_empty(client):
    r = client.get("/geocode?q=Nieistniejąca Ulica Xyz")
    assert r.status_code == 200
    assert r.get_json()["results"] == []


def test_geocode_disambiguates_streets_in_same_city(client):
    r = client.get("/geocode?q=łąkowa")
    displays = [x["display"] for x in r.get_json()["results"]]
    assert "Łąkowa, Białystok" in displays
    assert "Ogrodnicza, Białystok" not in displays


def test_geocode_voivodeship_disambiguates_duplicates(client):
    r = client.get("/geocode?q=słoneczna nowa wieś")
    displays = [x["display"] for x in r.get_json()["results"]]
    assert "Słoneczna, Nowa Wieś (mazowieckie)" in displays
    assert "Słoneczna, Nowa Wieś (wielkopolskie)" in displays


def test_geocode_voivodeship_narrows(client):
    r = client.get("/geocode?q=słoneczna nowa wieś wielkopolskie")
    displays = [x["display"] for x in r.get_json()["results"]]
    assert displays == ["Słoneczna, Nowa Wieś (wielkopolskie)"]


def test_search_addresses_missing_db_is_safe(app):
    from queries import search_addresses
    assert search_addresses("łąkowa białystok", "/no/such/addresses.db") == []
