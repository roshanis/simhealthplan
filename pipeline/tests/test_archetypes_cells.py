"""Tests for archetypes/cells.py — demographic cube, segment expansion, collapse."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from archetypes import cells
from archetypes.acs_marginals import ACSMarginals
from archetypes.constants import AGE_BANDS, ATTITUDE_SEGMENTS, INCOME_TIERS, RACE_ETH_GROUPS


@pytest.fixture
def marginals():
    return ACSMarginals(
        age_band_shares=dict(zip(AGE_BANDS, [0.3, 0.3, 0.3, 0.1])),
        race_eth_shares=dict(zip(RACE_ETH_GROUPS, [0.5, 0.2, 0.15, 0.1, 0.05])),
        income_tier_shares=dict(zip(INCOME_TIERS, [0.2, 0.4, 0.4])),
        income_tier_metadata={},
    )


def test_build_demographic_cells_shape_and_weight_conservation(marginals):
    df, iterations = cells.build_demographic_cells(marginals, population_total=1000.0)
    assert len(df) == len(AGE_BANDS) * len(INCOME_TIERS) * len(RACE_ETH_GROUPS)
    assert set(df.columns) >= {"age_band", "income_tier", "race_eth", "weight"}
    assert df["weight"].sum() == pytest.approx(1000.0, rel=1e-6)
    assert (df["weight"] > 0).all()
    assert iterations >= 1


def test_build_demographic_cells_matches_product_form_independence(marginals):
    df, _ = cells.build_demographic_cells(marginals, population_total=1000.0)
    row = df[(df.age_band == "65-69") & (df.income_tier == "low_dual_proxy") & (df.race_eth == "white_nh")]
    expected = 0.3 * 0.2 * 0.5 * 1000.0
    assert row["weight"].iloc[0] == pytest.approx(expected, rel=1e-6)


def test_expand_with_segments_produces_240_style_cells_and_conserves_weight(marginals):
    demo_cells, _ = cells.build_demographic_cells(marginals, population_total=1000.0)
    stratum_probs = {
        (age, income): dict(zip(ATTITUDE_SEGMENTS, [0.25, 0.25, 0.25, 0.25]))
        for age in AGE_BANDS
        for income in INCOME_TIERS
    }
    expanded = cells.expand_with_segments(demo_cells, stratum_probs)
    assert len(expanded) == len(demo_cells) * len(ATTITUDE_SEGMENTS)
    assert expanded["weight"].sum() == pytest.approx(1000.0, rel=1e-6)
    assert (expanded["weight"] > 0).all()


def test_expand_with_segments_applies_stratum_specific_probabilities(marginals):
    demo_cells, _ = cells.build_demographic_cells(marginals, population_total=1000.0)
    stratum_probs = {
        (age, income): dict(zip(ATTITUDE_SEGMENTS, [0.7, 0.1, 0.1, 0.1]))
        for age in AGE_BANDS
        for income in INCOME_TIERS
    }
    expanded = cells.expand_with_segments(demo_cells, stratum_probs)
    one_cell = expanded[
        (expanded.age_band == "65-69")
        & (expanded.income_tier == "low_dual_proxy")
        & (expanded.race_eth == "white_nh")
        & (expanded.attitude_segment == "price_sensitive")
    ]
    demo_weight = demo_cells[
        (demo_cells.age_band == "65-69") & (demo_cells.income_tier == "low_dual_proxy") & (demo_cells.race_eth == "white_nh")
    ]["weight"].iloc[0]
    assert one_cell["weight"].iloc[0] == pytest.approx(demo_weight * 0.7, rel=1e-6)


def _make_cells_df(n, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for age in AGE_BANDS:
        for income in INCOME_TIERS:
            for race in RACE_ETH_GROUPS:
                for segment in ATTITUDE_SEGMENTS:
                    rows.append(
                        {
                            "age_band": age,
                            "income_tier": income,
                            "race_eth": race,
                            "attitude_segment": segment,
                            "weight": rng.uniform(0.1, 100.0),
                        }
                    )
    df = pd.DataFrame(rows)
    df["weight"] = df["weight"] * (1000.0 / df["weight"].sum())
    return df


def test_collapse_cells_count_within_bounds_and_conserves_weight():
    cells_df = _make_cells_df(240)
    total_before = cells_df["weight"].sum()
    result = cells.collapse_cells(cells_df, min_count=30, max_count=80)

    assert 30 <= len(result) <= 80
    assert result["weight"].sum() == pytest.approx(total_before, rel=1e-6)
    assert (result["weight"] > 0).all()
    assert {"age_band", "income_tier", "race_eth", "attitude_segment", "weight", "dual_proxy", "is_other"} <= set(
        result.columns
    )


def test_collapse_cells_dual_proxy_flag_matches_income_tier_for_non_other_rows():
    cells_df = _make_cells_df(240)
    result = cells.collapse_cells(cells_df, min_count=30, max_count=80)
    concrete = result[~result["is_other"]]
    assert (concrete["dual_proxy"] == (concrete["income_tier"] == "low_dual_proxy")).all()


def test_collapse_cells_other_rows_have_unambiguous_dual_status():
    cells_df = _make_cells_df(240)
    result = cells.collapse_cells(cells_df, min_count=30, max_count=80)
    other = result[result["is_other"]]
    if not other.empty:
        # income_tier stays concrete (not "mixed") for Other rows too, since
        # buckets are grouped by (age_band, income_tier) -- only race/segment
        # are folded into "mixed".
        assert other["income_tier"].isin(INCOME_TIERS).all()
        assert (other["dual_proxy"] == (other["income_tier"] == "low_dual_proxy")).all()
        assert (other["race_eth"] == "mixed").all()
        assert (other["attitude_segment"] == "mixed").all()


def test_collapse_cells_respects_min_count_on_low_cardinality_input():
    # Only 16 cells total -- fewer than min_count=30 even if none collapse,
    # so collapse_cells must not error; it should just return what's there
    # topped up as much as possible (can't manufacture archetypes that don't
    # exist), i.e. count == number of distinct nonzero cells.
    rng = np.random.default_rng(1)
    rows = []
    for age in AGE_BANDS:
        for income in INCOME_TIERS[:1]:
            for race in RACE_ETH_GROUPS[:2]:
                for segment in ATTITUDE_SEGMENTS[:2]:
                    rows.append(
                        {
                            "age_band": age,
                            "income_tier": income,
                            "race_eth": race,
                            "attitude_segment": segment,
                            "weight": rng.uniform(1.0, 10.0),
                        }
                    )
    small_df = pd.DataFrame(rows)
    result = cells.collapse_cells(small_df, min_count=30, max_count=80)
    assert len(result) == len(small_df)
    assert result["weight"].sum() == pytest.approx(small_df["weight"].sum(), rel=1e-6)
