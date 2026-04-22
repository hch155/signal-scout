"""Pure-function tests for haversine distance — no DB, no Flask."""
import math
import pytest

pytestmark = pytest.mark.unit

from queries import haversine


def test_zero_distance():
    assert haversine(52.23, 21.00, 52.23, 21.00) == pytest.approx(0.0, abs=1e-9)


def test_warsaw_krakow_known_distance():
    # Warszawa (52.2297, 21.0122) → Kraków (50.0647, 19.9450)
    # Real great-circle distance ~252 km (within ±2 km is acceptable for haversine).
    d = haversine(52.2297, 21.0122, 50.0647, 19.9450)
    assert 250.0 < d < 254.0


def test_antipodes():
    # Halfway around Earth ~20015 km
    d = haversine(0.0, 0.0, 0.0, 180.0)
    assert 20010 < d < 20020


def test_symmetric():
    a = haversine(52.23, 21.00, 50.06, 19.94)
    b = haversine(50.06, 19.94, 52.23, 21.00)
    assert a == pytest.approx(b, abs=1e-9)


def test_short_distance_meters_scale():
    # Same building offset (~110m at this latitude per 0.001 degree)
    d_km = haversine(52.2300, 21.0000, 52.2310, 21.0000)
    assert 0.10 < d_km < 0.13


@pytest.mark.parametrize("lat1,lng1,lat2,lng2", [
    (52.23, 21.00, 52.24, 21.00),  # north
    (52.23, 21.00, 52.23, 21.01),  # east
    (52.23, 21.00, 52.22, 21.00),  # south
    (52.23, 21.00, 52.23, 20.99),  # west
])
def test_finite_positive(lat1, lng1, lat2, lng2):
    d = haversine(lat1, lng1, lat2, lng2)
    assert math.isfinite(d) and d > 0
