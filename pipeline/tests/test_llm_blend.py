"""Tests for llm/blend.py — Phase 4 logit/LLM blend.

Unit tests hand-verify the rank-bonus formula, the inertia-multiplier clamp,
and blended-distribution validity against small synthetic fixtures. The two
required bounded-deviation properties (per-archetype L1 distance < 0.35,
aggregate weighted share shift < 5pp) are validated as real-data integration
tests across all 80 committed archetypes, using a representative (not
adversarial) synthetic LLM output per archetype -- an LLM that broadly
agrees with the logit model's own ranking, which is the realistic case this
blend is designed for.
"""

from __future__ import annotations

import json

import pytest

from choice_model import choice_sets, predict, utility
from config.settings import settings
from llm import blend

OUTSIDE2 = predict.OUTSIDE_KEY_YEAR2


# --- rank_bonus ---------------------------------------------------------------


def test_rank_bonus_rank1_gets_full_alpha():
    result = blend.rank_bonus(["A", "B", "C"], alpha=0.35)
    assert result["A"] == pytest.approx(0.35)


def test_rank_bonus_last_rank_gets_zero():
    result = blend.rank_bonus(["A", "B", "C"], alpha=0.35)
    assert result["C"] == pytest.approx(0.0)


def test_rank_bonus_linear_between_ranks():
    result = blend.rank_bonus(["A", "B", "C"], alpha=0.35)
    # rank 2 of 3: 0.35 * (1 - 1/2) = 0.175
    assert result["B"] == pytest.approx(0.175)


def test_rank_bonus_single_item_gets_full_alpha():
    result = blend.rank_bonus(["A"], alpha=0.35)
    assert result == {"A": 0.35}


def test_rank_bonus_empty_list():
    assert blend.rank_bonus([], alpha=0.35) == {}


def test_rank_bonus_default_alpha_is_0_35():
    assert blend.ALPHA == pytest.approx(0.35)


# --- inertia_multiplier ---------------------------------------------------------


def test_inertia_multiplier_at_zero_switching_propensity_is_max():
    assert blend.inertia_multiplier(0.0) == pytest.approx(1.15)


def test_inertia_multiplier_at_one_switching_propensity_is_clamped_to_min():
    # raw = 1.15 - 0.30*1.0 = 0.85 -- exactly at the clamp boundary
    assert blend.inertia_multiplier(1.0) == pytest.approx(0.85)


def test_inertia_multiplier_at_half_is_one():
    assert blend.inertia_multiplier(0.5) == pytest.approx(1.0)


@pytest.mark.parametrize("sp", [-1.0, 2.0, 10.0, -100.0])
def test_inertia_multiplier_clamped_for_out_of_range_switching_propensity(sp):
    result = blend.inertia_multiplier(sp)
    assert blend.INERTIA_MULT_MIN <= result <= blend.INERTIA_MULT_MAX


def test_inertia_multiplier_monotonically_decreasing():
    values = [blend.inertia_multiplier(sp) for sp in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert values == sorted(values, reverse=True)


# --- blended_choice_probabilities: synthetic ------------------------------------


def _full_plan(key, **overrides):
    base = {
        "plan_key": key,
        "snp_type": "Not Applicable",
        "premium_total": 20.0,
        "moop_inn": 5000.0,
        "has_comprehensive_dental": True,
        "has_vision": True,
        "has_hearing_aids": False,
        "has_otc_or_flex": True,
        "star_rating": 4.0,
        "is_ppo": False,
    }
    base.update(overrides)
    return base


BASE_COEFFICIENTS = {
    "b_premium": -0.2,
    "b_moop": -0.15,
    "b_dental": 0.3,
    "b_vision_hearing": 0.25,
    "b_otc": 0.2,
    "b_star": 0.4,
    "b_ppo": 0.1,
    "b_inertia": 4.0,
    "b_outside": -1.0,
}


def test_blended_probabilities_are_a_valid_distribution():
    plans = [_full_plan("A"), _full_plan("B"), _full_plan("C")]
    prior = {"A": 0.2, "B": 0.1, OUTSIDE2: 0.7}
    result = blend.blended_choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE2, ["A", "B", "C", OUTSIDE2], 0.5)
    assert sum(result.values()) == pytest.approx(1.0)
    assert all(0.0 <= p <= 1.0 for p in result.values())
    assert set(result.keys()) == {"A", "B", "C", OUTSIDE2}


def test_blended_probabilities_reduce_to_pure_logit_when_alpha_zero_and_switching_propensity_half():
    """alpha=0 removes the rank bonus; switching_propensity=0.5 makes the
    inertia multiplier exactly 1.0 -- so the blend should exactly reproduce
    utility.choice_probabilities."""
    plans = [_full_plan("A"), _full_plan("B")]
    prior = {"A": 0.3, OUTSIDE2: 0.7}
    pure = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE2)
    blended = blend.blended_choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE2, ["A", "B", OUTSIDE2], 0.5, alpha=0.0)
    assert blended == pytest.approx(pure)


def test_rank1_plan_gets_higher_probability_than_pure_logit():
    plans = [_full_plan("A"), _full_plan("B")]
    prior = {"A": 0.0, "B": 0.0, OUTSIDE2: 1.0}  # symmetric prior: A and B tie under pure logit
    pure = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE2)
    # B ranked dead last (rank 3 of 3) gets exactly zero rank bonus, isolating
    # the effect of A's rank-1 bonus on the A-vs-B comparison.
    blended = blend.blended_choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE2, ["A", OUTSIDE2, "B"], 0.5)
    assert pure["A"] == pytest.approx(pure["B"])  # sanity: symmetric baseline
    assert blended["A"] > pure["A"]  # ranked #1 gets a boost
    assert blended["A"] > blended["B"]  # ranked #1 now clearly beats last-ranked B


def test_low_switching_propensity_strengthens_status_quo_relative_to_high():
    plans = [_full_plan("A")]
    prior = {"A": 0.9, OUTSIDE2: 0.1}
    low_switch = blend.blended_choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE2, ["A", OUTSIDE2], 0.0)
    high_switch = blend.blended_choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE2, ["A", OUTSIDE2], 1.0)
    assert low_switch["A"] > high_switch["A"]


def test_blend_does_not_mutate_input_coefficients():
    plans = [_full_plan("A")]
    prior = {"A": 0.5, OUTSIDE2: 0.5}
    original = dict(BASE_COEFFICIENTS)
    blend.blended_choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE2, ["A", OUTSIDE2], 0.9)
    assert BASE_COEFFICIENTS == original


# --- l1_distance ------------------------------------------------------------------


def test_l1_distance_identical_distributions_is_zero():
    d = {"A": 0.5, "B": 0.5}
    assert blend.l1_distance(d, d) == pytest.approx(0.0)


def test_l1_distance_disjoint_distributions():
    a = {"A": 1.0}
    b = {"B": 1.0}
    assert blend.l1_distance(a, b) == pytest.approx(2.0)


# --- real-data integration: bounded-deviation properties -------------------------


def _real_data_available() -> bool:
    return (
        (settings.PROCESSED_DIR / "archetypes.json").exists()
        and (settings.PROCESSED_DIR / "plans_2025.json").exists()
        and (settings.PROCESSED_DIR / "coefficients.json").exists()
        and (settings.INTERIM_DIR / "plan_crosswalk_2024_2025.parquet").exists()
    )


def _load_real():
    archetypes = json.loads((settings.PROCESSED_DIR / "archetypes.json").read_text())["archetypes"]
    plans_2025 = json.loads((settings.PROCESSED_DIR / "plans_2025.json").read_text())["plans"]
    coefficients = json.loads((settings.PROCESSED_DIR / "coefficients.json").read_text())
    crosswalk_map = predict.load_crosswalk_map()
    return archetypes, plans_2025, coefficients, crosswalk_map


@pytest.mark.integration
def test_real_blend_bounded_l1_deviation_per_archetype():
    """Property: with a representative (logit-agreeing) LLM ranking and a
    moderate switching_propensity, no archetype's blended distribution
    diverges from its pure logit distribution by more than 0.35 in L1."""
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    archetypes, plans_2025, coefficients, crosswalk_map = _load_real()
    base_coefficients = coefficients["base_coefficients"]

    logit_result = predict.predict_all(archetypes, plans_2025, base_coefficients, crosswalk_map)

    for archetype in archetypes:
        aid = archetype["id"]
        per = logit_result["per_archetype"][aid]
        eligible_plans = choice_sets.eligible_plans(archetype, plans_2025)

        # Representative (non-adversarial) mock LLM output: ranks alternatives
        # in the logit model's own probability order, moderate switching_propensity.
        ranked = sorted(per["probs"], key=lambda key: -per["probs"][key])

        blended = blend.blended_choice_probabilities(
            base_coefficients, archetype["attitude_segment"], eligible_plans, per["renormalized_prior"], predict.OUTSIDE_KEY_YEAR2, ranked, 0.5
        )

        l1 = blend.l1_distance(per["probs"], blended)
        assert l1 < 0.35, f"{aid}: L1 distance {l1} >= 0.35"


@pytest.mark.integration
def test_real_blend_bounded_aggregate_share_shift():
    """Property: the size-weighted aggregate share shift between logit-only
    and blended predictions, summed across all plans + outside, is bounded
    (< 5pp total) under the same representative LLM output."""
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    archetypes, plans_2025, coefficients, crosswalk_map = _load_real()
    base_coefficients = coefficients["base_coefficients"]

    logit_result = predict.predict_all(archetypes, plans_2025, base_coefficients, crosswalk_map)

    blended_by_archetype = {}
    for archetype in archetypes:
        aid = archetype["id"]
        per = logit_result["per_archetype"][aid]
        eligible_plans = choice_sets.eligible_plans(archetype, plans_2025)
        ranked = sorted(per["probs"], key=lambda key: -per["probs"][key])
        blended_by_archetype[aid] = blend.blended_choice_probabilities(
            base_coefficients, archetype["attitude_segment"], eligible_plans, per["renormalized_prior"], predict.OUTSIDE_KEY_YEAR2, ranked, 0.5
        )

    aggregate_blended = predict.aggregate_weighted_shares(archetypes, blended_by_archetype)
    aggregate_logit = logit_result["aggregate_shares"]

    total_shift_pp = sum(abs(aggregate_blended.get(k, 0.0) - aggregate_logit.get(k, 0.0)) for k in set(aggregate_logit) | set(aggregate_blended)) * 100
    assert total_shift_pp < 5.0, f"aggregate shift {total_shift_pp}pp >= 5pp"
