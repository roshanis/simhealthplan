"""Tests for archetypes/traits.py — short human-readable persona trait phrases."""

from __future__ import annotations

import pandas as pd

from archetypes import traits


def _row(**overrides):
    base = {
        "age_band": "70-74",
        "income_tier": "middle",
        "race_eth": "white_nh",
        "attitude_segment": "price_sensitive",
        "dual_proxy": False,
        "is_other": False,
    }
    base.update(overrides)
    return pd.Series(base)


def test_build_traits_returns_nonempty_list_of_strings():
    result = traits.build_traits(_row())
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(t, str) and t for t in result)


def test_build_traits_reflects_price_sensitive_segment():
    result = traits.build_traits(_row(attitude_segment="price_sensitive"))
    assert any("price" in t.lower() for t in result)


def test_build_traits_reflects_benefit_maximizer_segment():
    result = traits.build_traits(_row(attitude_segment="benefit_maximizer"))
    assert any("dental" in t.lower() or "vision" in t.lower() or "benefit" in t.lower() for t in result)


def test_build_traits_reflects_dual_proxy():
    result = traits.build_traits(_row(dual_proxy=True, income_tier="low_dual_proxy"))
    assert any("dual" in t.lower() or "cost" in t.lower() for t in result)


def test_build_traits_reflects_oldest_old_age_band():
    result = traits.build_traits(_row(age_band="85+"))
    assert any("85" in t or "oldest" in t.lower() for t in result)


def test_build_traits_handles_mixed_other_catchall():
    result = traits.build_traits(_row(attitude_segment="mixed", is_other=True))
    assert len(result) > 0


def test_build_traits_never_mentions_race_or_ethnicity():
    # No evidence-based race-conditioned attitude signal exists in the
    # underlying MCBS data -- traits must not fabricate one.
    for race in ["white_nh", "hispanic", "black_nh", "asian_nh", "other_multi_nh", "mixed"]:
        result = traits.build_traits(_row(race_eth=race))
        joined = " ".join(result).lower()
        for banned in ["hispanic", "white", "black", "asian", "race", "ethnic"]:
            assert banned not in joined


def test_build_traits_no_duplicate_phrases():
    result = traits.build_traits(_row(attitude_segment="brand_loyal", dual_proxy=True, age_band="85+"))
    assert len(result) == len(set(result))
