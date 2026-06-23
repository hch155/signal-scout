"""Address-search geocode endpoint: PL filtering + validation, geocoder mocked."""
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.integration


def _photon(features):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json = MagicMock(return_value={"features": features})
    return m


def test_geocode_returns_pl_result(client):
    feat = {
        "geometry": {"coordinates": [21.0122, 52.2297]},
        "properties": {"name": "Marszałkowska", "city": "Warszawa",
                       "state": "Mazowieckie", "countrycode": "PL"},
    }
    with patch("requests.get", return_value=_photon([feat])):
        r = client.get("/geocode?q=Marszalkowska Warszawa")
    assert r.status_code == 200
    results = r.get_json()["results"]
    assert len(results) == 1
    assert results[0]["lat"] == 52.2297 and results[0]["lng"] == 21.0122
    assert "Warszawa" in results[0]["display"]


def test_geocode_short_query_returns_empty_without_calling_geocoder(client):
    with patch("requests.get") as gw:
        r = client.get("/geocode?q=ab")
    assert r.status_code == 200
    assert r.get_json()["results"] == []
    gw.assert_not_called()


def test_geocode_filters_non_pl(client):
    feat = {"geometry": {"coordinates": [13.4, 52.5]},
            "properties": {"name": "Berlin", "countrycode": "DE"}}
    with patch("requests.get", return_value=_photon([feat])):
        r = client.get("/geocode?q=Berlin")
    assert r.get_json()["results"] == []


def test_geocode_dedupes_identical_display(client):
    # Photon returns one feature per street segment -> same display, diff coords.
    feats = [{
        "geometry": {"coordinates": [23.171 + i * 0.001, 53.138 + i * 0.001]},
        "properties": {"name": "Łąkowa", "city": "Białystok",
                       "state": "podlaskie", "countrycode": "PL"},
    } for i in range(4)]
    with patch("requests.get", return_value=_photon(feats)):
        r = client.get("/geocode?q=Lakowa Bialystok")
    results = r.get_json()["results"]
    assert len(results) == 1


def test_geocode_geocoder_down_is_safe(client):
    with patch("requests.get", side_effect=Exception("boom")):
        r = client.get("/geocode?q=Krakow")
    assert r.status_code == 502
    assert r.get_json()["results"] == []
