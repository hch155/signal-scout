"""Pure-function tests for sort_frequency_bands."""
import pytest

pytestmark = pytest.mark.unit

from queries import sort_frequency_bands


def test_priority_ordering_5g_first_gsm_last():
    out = sort_frequency_bands(["GSM900", "5G2100", "LTE1800", "UMTS900"])
    # 5G > LTE > UMTS > GSM
    families = [b[:3] if b.startswith("LTE") or b.startswith("UMTS") or b.startswith("GSM") else b[:2] for b in out]
    # Translate to a single key
    fam_rank = {"5G": 0, "LTE": 1, "UMT": 2, "GSM": 3}
    ranks = [fam_rank[f] for f in families]
    assert ranks == sorted(ranks)


def test_within_family_higher_frequency_first():
    out = sort_frequency_bands(["LTE800", "LTE2600", "LTE1800", "LTE2100"])
    assert out == ["LTE2600", "LTE2100", "LTE1800", "LTE800"]


def test_empty_list():
    assert sort_frequency_bands([]) == []


def test_single_band():
    assert sort_frequency_bands(["LTE1800"]) == ["LTE1800"]


def test_idempotent():
    bands = ["GSM900", "5G2100", "LTE1800", "UMTS900", "5G3600", "LTE800"]
    once = sort_frequency_bands(bands)
    twice = sort_frequency_bands(once)
    assert once == twice


def test_unknown_band_lands_at_end():
    out = sort_frequency_bands(["LTE1800", "MYSTERY42", "5G2100"])
    assert out[-1] == "MYSTERY42"
