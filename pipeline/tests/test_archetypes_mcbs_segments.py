"""Tests for archetypes/mcbs_segments.py — MCBS attitude segmentation.

TDD against small synthetic MCBS-shaped DataFrames (string-coded values,
mirroring the real mcbs_subset.parquet: numeric codes as strings, 'D'/'R'/'N'
for don't-know/refused/not-ascertained, NaN for inapplicable). The
integration test exercises the real data/interim/mcbs_subset.parquet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from archetypes import mcbs_segments
from archetypes.constants import AGE_BANDS, ATTITUDE_SEGMENTS, INCOME_TIERS
from config.settings import settings


def test_recode_maps_known_codes_and_nulls_unknowns():
    series = pd.Series(["1", "2", "D", "R", None])
    recoded = mcbs_segments._recode(series, {1: 1.0, 2: 0.0})
    assert recoded.tolist()[:2] == [1.0, 0.0]
    assert recoded.iloc[2:].isna().all()


def test_compute_raw_score_averages_available_recoded_columns():
    df = pd.DataFrame(
        {
            "A": ["1", "2", "1"],  # -> 1.0, 0.0, 1.0
            "B": ["2", "1", None],  # -> 0.0, 1.0, NaN
        }
    )
    variables = [("A", {1: 1.0, 2: 0.0}), ("B", {1: 1.0, 2: 0.0})]
    score = mcbs_segments.compute_raw_score(df, variables)
    assert score.tolist() == pytest.approx([0.5, 0.5, 1.0])


def test_weighted_percentile_rank_orders_correctly_with_ties():
    values = np.array([10.0, 20.0, 20.0, 30.0])
    weights = np.array([1.0, 1.0, 1.0, 1.0])
    ranks = mcbs_segments.weighted_percentile_rank(values, weights)
    # lowest value -> lowest rank, highest -> highest, ties share a rank.
    assert ranks[0] < ranks[1]
    assert ranks[1] == pytest.approx(ranks[2])
    assert ranks[3] > ranks[1]
    assert (ranks >= 0).all() and (ranks <= 1).all()


def test_weighted_percentile_rank_respects_weights():
    # A single heavily-weighted low value should pull the rank of a mid
    # value up (more mass below it).
    values = np.array([1.0, 2.0, 3.0])
    weights_uniform = np.array([1.0, 1.0, 1.0])
    weights_skewed = np.array([100.0, 1.0, 1.0])
    r_uniform = mcbs_segments.weighted_percentile_rank(values, weights_uniform)
    r_skewed = mcbs_segments.weighted_percentile_rank(values, weights_skewed)
    assert r_skewed[1] > r_uniform[1]


def test_classify_segment_picks_argmax_percentile_deterministically():
    # Four respondents, each clearly dominant in one score.
    df = pd.DataFrame(
        {
            "price_sensitive_score": [1.0, 0.0, 0.0, 0.0],
            "benefit_maximizer_score": [0.0, 1.0, 0.0, 0.0],
            "brand_loyal_score": [0.0, 0.0, 1.0, 0.0],
            "health_status_driven_score": [0.0, 0.0, 0.0, 1.0],
            "PUFFWGT": ["1.0", "1.0", "1.0", "1.0"],
        }
    )
    segments = mcbs_segments.classify_segment(df, weight_col="PUFFWGT")
    assert segments.tolist() == ATTITUDE_SEGMENTS


def test_classify_segment_tie_break_is_deterministic_priority_order():
    # Exact tie across all four scores -> first in ATTITUDE_SEGMENTS order.
    df = pd.DataFrame(
        {
            "price_sensitive_score": [0.5],
            "benefit_maximizer_score": [0.5],
            "brand_loyal_score": [0.5],
            "health_status_driven_score": [0.5],
            "PUFFWGT": ["1.0"],
        }
    )
    segments = mcbs_segments.classify_segment(df, weight_col="PUFFWGT")
    assert segments.tolist() == ["price_sensitive"]


def test_national_segment_shares_sum_to_one():
    df = pd.DataFrame(
        {
            "attitude_segment": ["price_sensitive", "price_sensitive", "brand_loyal"],
            "PUFFWGT": ["1.0", "1.0", "2.0"],
        }
    )
    shares = mcbs_segments.national_segment_shares(df, weight_col="PUFFWGT")
    assert sum(shares.values()) == pytest.approx(1.0)
    assert shares["price_sensitive"] == pytest.approx(0.5)
    assert shares["brand_loyal"] == pytest.approx(0.5)


def test_mcbs_stratum_maps_age_and_income_and_drops_under_65():
    df = pd.DataFrame(
        {
            "DEM_AGE": ["1", "2", "3", "2"],
            "DEM_INCOME": ["1", "1", "2", "2"],
        }
    )
    stratum = mcbs_segments.mcbs_stratum(df)
    assert stratum.iloc[0] is None or pd.isna(stratum.iloc[0])
    assert stratum.iloc[1] == "65_74|lt25k"
    assert stratum.iloc[2] == "75_plus|ge25k"
    assert stratum.iloc[3] == "65_74|ge25k"


def test_stratum_conditional_probs_sum_to_one_per_stratum():
    df = pd.DataFrame(
        {
            "mcbs_stratum": ["65_74|lt25k", "65_74|lt25k", "75_plus|ge25k"],
            "attitude_segment": ["price_sensitive", "brand_loyal", "health_status_driven"],
            "PUFFWGT": ["1.0", "1.0", "1.0"],
        }
    )
    probs = mcbs_segments.stratum_conditional_probs(df, weight_col="PUFFWGT")
    assert set(probs.keys()) == {"65_74|lt25k", "75_plus|ge25k"}
    for stratum_probs in probs.values():
        assert sum(stratum_probs.values()) == pytest.approx(1.0)


def test_segment_probabilities_by_acs_stratum_covers_all_12_combos():
    mcbs_stratum_probs = {
        "65_74|lt25k": {s: 0.25 for s in ATTITUDE_SEGMENTS},
        "65_74|ge25k": {s: 0.25 for s in ATTITUDE_SEGMENTS},
        "75_plus|lt25k": {s: 0.25 for s in ATTITUDE_SEGMENTS},
        "75_plus|ge25k": {s: 0.25 for s in ATTITUDE_SEGMENTS},
    }
    by_acs = mcbs_segments.segment_probabilities_by_acs_stratum(mcbs_stratum_probs)
    assert len(by_acs) == len(AGE_BANDS) * len(INCOME_TIERS)
    for age_band in AGE_BANDS:
        for income_tier in INCOME_TIERS:
            probs = by_acs[(age_band, income_tier)]
            assert sum(probs.values()) == pytest.approx(1.0)
    # 65-69 and 70-74 both map to the same native MCBS "65_74" bucket.
    assert by_acs[("65-69", "middle")] == by_acs[("70-74", "middle")]
    # middle and higher both map to the native MCBS "ge25k" bucket.
    assert by_acs[("75-84", "middle")] == by_acs[("75-84", "higher")]


@pytest.mark.integration
def test_build_segments_real_mcbs_subset():
    path = settings.INTERIM_DIR / "mcbs_subset.parquet"
    if not path.exists():
        pytest.skip(f"{path} not present; run `make ingest` first")
    df = pd.read_parquet(path)
    segmentation = mcbs_segments.build_segments(df)

    assert set(segmentation.national_shares) == set(ATTITUDE_SEGMENTS)
    assert sum(segmentation.national_shares.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(v > 0 for v in segmentation.national_shares.values())

    assert len(segmentation.stratum_probabilities) == len(AGE_BANDS) * len(INCOME_TIERS)
    for probs in segmentation.stratum_probabilities.values():
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)
        assert all(v >= 0 for v in probs.values())

    assert segmentation.n_respondents_used > 5000
