"""Pure-function tests for real5g_rollout: the n78 (3.5 GHz) aggregation,
band threshold, voivodeship attribution, and operator labelling."""
import sqlite3

import pytest

from real5g_rollout import (
    _is_n78,
    operator_label,
    real_5g_rollout,
    voivodeship_for,
)

pytestmark = pytest.mark.unit

ORANGE = "Orange Polska S.A."
PLAY = "P4 sp. z o.o."
PLUS = "Polkomtel sp. z o.o."

# (provider, location, lat, lng, band)
WARSAW = (52.2300, 21.0100)
KRAKOW = (50.0600, 19.9400)
GDANSK = (54.3500, 18.6500)


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE base_station (id INTEGER PRIMARY KEY, "
        "service_provider VARCHAR, location VARCHAR, "
        "latitude FLOAT, longitude FLOAT, frequency_band VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO base_station "
        "(service_provider, location, latitude, longitude, frequency_band) "
        "VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_counts_distinct_sites_per_operator(tmp_path):
    db = tmp_path / "stations.db"
    _make_db(db, [
        # Orange: two distinct Warsaw sites (one has an extra LTE row +
        # an extra n78 band — both must collapse to a single site).
        (ORANGE, "wa-1", *WARSAW, "5G3600"),
        (ORANGE, "wa-1", *WARSAW, "5G3500"),
        (ORANGE, "wa-1", *WARSAW, "LTE800"),
        (ORANGE, "wa-2", *WARSAW, "5G3600"),
        # Orange: one Kraków site.
        (ORANGE, "kr-1", *KRAKOW, "5G3500"),
        # Play: one Warsaw site, one Gdańsk site.
        (PLAY, "wa-3", *WARSAW, "5G3600"),
        (PLAY, "gd-1", *GDANSK, "5G3600"),
    ])
    out = real_5g_rollout(str(db))
    assert out["by_operator"] == {ORANGE: 3, PLAY: 2}
    assert out["total_sites"] == 5
    assert sum(out["by_operator"].values()) == out["total_sites"]
    assert sum(out["by_voivodeship"].values()) == out["total_sites"]


def test_excludes_non_n78_and_honeypot(tmp_path):
    db = tmp_path / "stations.db"
    _make_db(db, [
        (ORANGE, "a", *WARSAW, "5G3600"),
        # Sub-3400 MHz 5G bands are NOT n78 / Real-5G.
        (PLUS, "b", *WARSAW, "5G2100"),
        (PLUS, "c", *WARSAW, "5G700"),
        (PLUS, "d", *WARSAW, "5G3300"),
        # Honeypot rows never count.
        ("__HONEYPOT__", "h", *WARSAW, "5G3600"),
    ])
    out = real_5g_rollout(str(db))
    assert out["by_operator"] == {ORANGE: 1}
    assert out["total_sites"] == 1


def test_voivodeship_attribution(tmp_path):
    db = tmp_path / "stations.db"
    _make_db(db, [
        (ORANGE, "wa", *WARSAW, "5G3600"),
        (PLAY, "kr", *KRAKOW, "5G3500"),
        (PLAY, "gd", *GDANSK, "5G3600"),
    ])
    out = real_5g_rollout(str(db))
    assert out["by_voivodeship"] == {
        "mazowieckie": 1,
        "małopolskie": 1,
        "pomorskie": 1,
    }


def test_missing_db_returns_zeros(tmp_path):
    out = real_5g_rollout(str(tmp_path / "nope.db"))
    assert out == {"by_operator": {}, "by_voivodeship": {}, "total_sites": 0}


def test_is_n78_threshold():
    assert _is_n78("5G3600") is True
    assert _is_n78("5G3500") is True
    assert _is_n78("5G3300") is False
    assert _is_n78("5G2100") is False
    assert _is_n78("LTE800") is False
    assert _is_n78(None) is False


def test_voivodeship_for_known_points():
    assert voivodeship_for(*WARSAW) == "mazowieckie"
    assert voivodeship_for(*KRAKOW) == "małopolskie"
    assert voivodeship_for(*GDANSK) == "pomorskie"
    assert voivodeship_for(None, None) == "unknown"


def test_operator_label():
    assert operator_label(ORANGE) == "Orange"
    assert operator_label(PLAY) == "Play"
    assert operator_label(PLUS) == "Plus"
    assert operator_label("T-Mobile Polska S.A.") == "T-Mobile"
    assert operator_label("Some Other Telco") == "Some Other Telco"
