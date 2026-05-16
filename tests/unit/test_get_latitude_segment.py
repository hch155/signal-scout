"""Pure-function tests for get_latitude_segment."""
import pytest

pytestmark = pytest.mark.unit

from queries import get_latitude_segment  # noqa: E402


def test_base_latitude_is_segment_zero():
    assert get_latitude_segment(49.0) == 0


def test_warsaw_segment():
    # 52.23 - 49.0 = 3.23 → 32
    assert get_latitude_segment(52.23) == 32


def test_north_pole_of_supported_area():
    # 55.5 - 49.0 = 6.5 → 65
    assert get_latitude_segment(55.5) == 65


def test_monotonic_increasing():
    """Higher latitude → equal or greater segment, never less."""
    prev = get_latitude_segment(49.0)
    for tenth in range(1, 70):
        cur = get_latitude_segment(49.0 + tenth * 0.1)
        assert cur >= prev
        prev = cur


def test_returns_int():
    assert isinstance(get_latitude_segment(52.23), int)


@pytest.mark.parametrize("lat,expected", [
    (49.05, 0),
    (49.1, 1),
    (50.0, 10),
    (54.35, 53),  # Gdańsk
])
def test_known_segments(lat, expected):
    assert get_latitude_segment(lat) == expected
