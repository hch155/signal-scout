"""Pure-function tests for the best-operator ranking — no DB, no Flask."""
import pytest

pytestmark = pytest.mark.unit

from best_operator import (  # noqa: E402
    rank_operators,
    operator_slug,
    has_referral,
    build_referral_url,
    build_rationale,
    REFERRAL_LINKS,
)


def make_op(operator, tier, *, real_5g=False, techs=None, dist=1.0, bands=None, real5g_km=None):
    if real_5g and real5g_km is None:
        real5g_km = dist  # default: the n78 mast IS the nearest mast
    return {
        "operator": operator,
        "service_provider": operator,
        "nearest_distance_km": dist,
        "signal_tier": tier,
        "technologies": techs or {"5G": False, "LTE": True, "3G": False, "GSM": False},
        "real_5g": real_5g,
        "real5g_km": real5g_km,
        "5g_bands_mhz": bands or [],
    }


_FULL = {"5G": True, "LTE": True, "3G": False, "GSM": False}


def test_winner_is_single_highest_score_and_sorted_desc():
    a = make_op("Orange", "Excellent", real_5g=True, techs=_FULL)
    b = make_op("Play", "Good", techs=_FULL)
    c = make_op("Plus", "Fair")
    ranked = rank_operators({"operators": [c, b, a]})

    assert [o["operator"] for o in ranked] == ["Orange", "Play", "Plus"]
    assert ranked[0]["recommended"] is True
    assert sum(1 for o in ranked if o["recommended"]) == 1
    scores = [o["rank_score"] for o in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rank_score_sums_tier_real5g_bonus_and_tech_depth():
    a = make_op("Orange", "Excellent", real_5g=True, techs=_FULL)
    ranked = rank_operators([a])
    # 40 (Excellent) + 25 (real 5G) + 12 (5G) + 8 (LTE)
    assert ranked[0]["rank_score"] == 85


def test_real_5g_outranks_a_closer_non_real_5g_operator():
    far_real = make_op("Plus", "Excellent", real_5g=True, techs=_FULL, dist=1.2)
    near_plain = make_op("Orange", "Excellent", techs=_FULL, dist=0.2)
    ranked = rank_operators([near_plain, far_real])
    assert ranked[0]["operator"] == "Plus"
    assert ranked[0]["recommended"] is True


def test_tie_break_prefers_nearer_mast():
    far = make_op("Orange", "Good", techs=_FULL, dist=2.0)
    near = make_op("Play", "Good", techs=_FULL, dist=0.5)
    ranked = rank_operators([far, near])
    assert ranked[0]["rank_score"] == ranked[1]["rank_score"]
    assert ranked[0]["operator"] == "Play"


def test_empty_inputs_return_empty_list():
    assert rank_operators({"operators": []}) == []
    assert rank_operators({}) == []
    assert rank_operators([]) == []
    assert rank_operators(None) == []


def test_accepts_full_verdict_dict_and_bare_list_equivalently():
    ops = [make_op("Orange", "Good", techs=_FULL), make_op("Plus", "Poor")]
    from_dict = rank_operators({"operators": ops, "signal_tier": "Good"})
    from_list = rank_operators(ops)
    assert [o["operator"] for o in from_dict] == [o["operator"] for o in from_list]


def test_input_operators_are_not_mutated():
    op = make_op("Orange", "Good", techs=_FULL)
    rank_operators([op])
    assert "rank_score" not in op
    assert "recommended" not in op
    assert "rationale" not in op


def test_recommended_rationale_has_real_5g_phrases_in_both_languages():
    a = make_op("Orange", "Excellent", real_5g=True, techs=_FULL)
    winner = rank_operators([a])[0]
    assert winner["rationale"]["en"] == "Best for you: nearest 5G mast + real 5G (3.5 GHz)"
    assert winner["rationale"]["pl"] == "Najlepszy dla Ciebie: najbliższy maszt 5G + prawdziwe 5G (3,5 GHz)"


def test_recommended_rationale_names_distance_when_n78_not_nearest():
    # Nearest Orange mast is LTE-only at 0.1 km; the real-5G (n78) mast is 2 km away.
    # The copy must state the 3.5 GHz distance, not imply the nearest mast is n78.
    a = make_op("Orange", "Excellent", real_5g=True, techs=_FULL, dist=0.1, real5g_km=2.0)
    winner = rank_operators([a])[0]
    assert winner["rationale"]["en"] == "Best for you: nearest mast + real 5G (3.5 GHz) 2.0 km away"
    assert winner["rationale"]["pl"] == "Najlepszy dla Ciebie: najbliższy maszt + prawdziwe 5G (3,5 GHz) 2.0 km stąd"
    assert "nearest 5G mast" not in winner["rationale"]["en"]
    assert "najbliższy maszt 5G" not in winner["rationale"]["pl"]


def test_non_recommended_rationale_uses_tier_and_localized_labels():
    a = make_op("Orange", "Excellent", real_5g=True, techs=_FULL)
    b = make_op("Play", "Good", techs=_FULL)
    ranked = rank_operators([a, b])
    runner_up = next(o for o in ranked if not o["recommended"])
    assert runner_up["rationale"]["en"] == "Good signal · 5G coverage"
    assert runner_up["rationale"]["pl"] == "Dobry sygnał · zasięg 5G"


def test_build_rationale_lte_only_recommended():
    op = make_op("Plus", "Fair", techs={"5G": False, "LTE": True, "3G": False, "GSM": False})
    r = build_rationale(op, recommended=True)
    assert r["en"] == "Best for you: nearest mast + fair signal"
    assert r["pl"].startswith("Najlepszy dla Ciebie:")


def test_operator_slug_known_and_fallback():
    assert operator_slug("T-Mobile") == "tmobile"
    assert operator_slug("Play") == "play"
    assert operator_slug("Orange") == "orange"
    assert operator_slug("Plus") == "plus"
    assert operator_slug("Some New Carrier") == "some-new-carrier"
    assert operator_slug("") == ""


def test_ranked_operator_carries_slug():
    ranked = rank_operators([make_op("T-Mobile", "Good", techs=_FULL)])
    assert ranked[0]["slug"] == "tmobile"


def test_referral_link_map_and_url_building():
    assert has_referral("orange") is True
    assert has_referral("not-an-operator") is False

    url = build_referral_url("orange")
    assert url.startswith(REFERRAL_LINKS["orange"]["url"].split("?")[0])
    assert "utm_source=signal-scout" in url
    assert "utm_medium=referral" in url
    assert "utm_campaign=best-operator" in url
    assert "subid=ss-orange" in url
    assert "utm_content=ss-orange" in url

    assert build_referral_url("unknown") is None


def test_build_referral_url_preserves_existing_partner_query():
    REFERRAL_LINKS["testop"] = {"url": "https://aff.example/landing?ref=42", "subid": "ss-x"}
    try:
        url = build_referral_url("testop")
        assert "ref=42" in url
        assert "utm_source=signal-scout" in url
        assert "subid=ss-x" in url
    finally:
        REFERRAL_LINKS.pop("testop", None)
