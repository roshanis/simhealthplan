"""Tests for choice_model/utility.py — pure multinomial-logit utility/softmax.

Property-focused: this module is PURE (no I/O, no globals) and gets ported
1:1 to TypeScript in a later phase, so tests exercise it purely through
plain dicts/lists, exactly as a TS caller would.
"""

from __future__ import annotations

import math

import pytest

from choice_model import utility

OUTSIDE_KEY = "other_or_no_ma_2024"

BASE_COEFFICIENTS = {
    "b_premium": -0.20,
    "b_moop": -0.15,
    "b_dental": 0.30,
    "b_vision_hearing": 0.25,
    "b_otc": 0.20,
    "b_star": 0.40,
    "b_ppo": 0.10,
    "b_inertia": 4.0,
    "b_outside": -1.0,
}


def _plan(key, **overrides):
    base = {
        "plan_key": key,
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


def _plans(n=5):
    return [_plan(f"P{i}", premium_total=10.0 * i) for i in range(n)]


def _prior(plans, outside=0.1):
    n = len(plans)
    each = (1.0 - outside) / n if n else 0.0
    prior = {p["plan_key"]: each for p in plans}
    prior[OUTSIDE_KEY] = outside
    return prior


# --- segment_coefficients ------------------------------------------------------


def test_segment_coefficients_mixed_is_identity():
    coeffs = utility.segment_coefficients(BASE_COEFFICIENTS, "mixed")
    assert coeffs == BASE_COEFFICIENTS


def test_segment_coefficients_unknown_segment_is_identity():
    coeffs = utility.segment_coefficients(BASE_COEFFICIENTS, "some_unknown_segment")
    assert coeffs == BASE_COEFFICIENTS


def test_segment_coefficients_price_sensitive_scales_premium_and_inertia():
    coeffs = utility.segment_coefficients(BASE_COEFFICIENTS, "price_sensitive")
    assert coeffs["b_premium"] == pytest.approx(BASE_COEFFICIENTS["b_premium"] * 1.6)
    assert coeffs["b_inertia"] == pytest.approx(BASE_COEFFICIENTS["b_inertia"] * 0.6)
    # untouched coefficients pass through unchanged
    assert coeffs["b_star"] == pytest.approx(BASE_COEFFICIENTS["b_star"])


def test_segment_coefficients_benefit_maximizer_scales_benefits():
    coeffs = utility.segment_coefficients(BASE_COEFFICIENTS, "benefit_maximizer")
    for name in ("b_dental", "b_vision_hearing", "b_otc"):
        assert coeffs[name] == pytest.approx(BASE_COEFFICIENTS[name] * 1.5)
    assert coeffs["b_premium"] == pytest.approx(BASE_COEFFICIENTS["b_premium"])


def test_segment_coefficients_brand_loyal_scales_inertia():
    coeffs = utility.segment_coefficients(BASE_COEFFICIENTS, "brand_loyal")
    assert coeffs["b_inertia"] == pytest.approx(BASE_COEFFICIENTS["b_inertia"] * 2.0)


def test_segment_coefficients_health_status_driven_scales_star_and_moop():
    coeffs = utility.segment_coefficients(BASE_COEFFICIENTS, "health_status_driven")
    assert coeffs["b_star"] == pytest.approx(BASE_COEFFICIENTS["b_star"] * 1.5)
    assert coeffs["b_moop"] == pytest.approx(BASE_COEFFICIENTS["b_moop"] * 1.3)


# --- plan_utility ---------------------------------------------------------------


def test_plan_utility_matches_hand_computed_formula():
    plan = _plan("P1", premium_total=50.0, moop_inn=6000.0, star_rating=4.5, is_ppo=True)
    prior_prob = 0.2
    u = utility.plan_utility(BASE_COEFFICIENTS, plan, prior_prob)
    expected = (
        BASE_COEFFICIENTS["b_premium"] * (50.0 / 10.0)
        + BASE_COEFFICIENTS["b_moop"] * (6000.0 / 1000.0)
        + BASE_COEFFICIENTS["b_dental"] * 1.0
        + BASE_COEFFICIENTS["b_vision_hearing"] * ((1.0 + 0.0) / 2.0)
        + BASE_COEFFICIENTS["b_otc"] * 1.0
        + BASE_COEFFICIENTS["b_star"] * (4.5 - 3.5)
        + BASE_COEFFICIENTS["b_ppo"] * 1.0
        + BASE_COEFFICIENTS["b_inertia"] * prior_prob
    )
    assert u == pytest.approx(expected)


def test_outside_utility_matches_formula():
    u = utility.outside_utility(BASE_COEFFICIENTS, 0.3)
    expected = BASE_COEFFICIENTS["b_outside"] + BASE_COEFFICIENTS["b_inertia"] * 0.3
    assert u == pytest.approx(expected)


# --- choice_probabilities: core properties --------------------------------------


def test_probabilities_sum_to_one():
    plans = _plans(6)
    prior = _prior(plans)
    probs = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE_KEY)
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(probs.keys()) == {p["plan_key"] for p in plans} | {OUTSIDE_KEY}


def test_probabilities_sum_to_one_across_all_segments():
    plans = _plans(4)
    prior = _prior(plans)
    for segment in ("price_sensitive", "benefit_maximizer", "brand_loyal", "health_status_driven", "mixed"):
        probs = utility.choice_probabilities(BASE_COEFFICIENTS, segment, plans, prior, OUTSIDE_KEY)
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)


def test_lowering_premium_strictly_increases_probability():
    plans = _plans(5)
    prior = _prior(plans)
    probs_before = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE_KEY)

    cheaper_plans = [dict(p) for p in plans]
    cheaper_plans[0] = dict(cheaper_plans[0], premium_total=cheaper_plans[0]["premium_total"] - 5.0)
    probs_after = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", cheaper_plans, prior, OUTSIDE_KEY)

    key = plans[0]["plan_key"]
    assert probs_after[key] > probs_before[key]


def test_raising_moop_strictly_decreases_probability():
    plans = _plans(5)
    prior = _prior(plans)
    probs_before = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE_KEY)

    worse_plans = [dict(p) for p in plans]
    worse_plans[0] = dict(worse_plans[0], moop_inn=worse_plans[0]["moop_inn"] + 2000.0)
    probs_after = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", worse_plans, prior, OUTSIDE_KEY)

    key = plans[0]["plan_key"]
    assert probs_after[key] < probs_before[key]


def test_single_plan_plus_outside_probabilities_are_softmax_of_two():
    plan = _plan("ONLY")
    prior = {"ONLY": 0.4, OUTSIDE_KEY: 0.6}
    probs = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", [plan], prior, OUTSIDE_KEY)
    coeffs = utility.segment_coefficients(BASE_COEFFICIENTS, "mixed")
    u_plan = utility.plan_utility(coeffs, plan, 0.4)
    u_out = utility.outside_utility(coeffs, 0.6)
    denom = math.exp(u_plan) + math.exp(u_out)
    assert probs["ONLY"] == pytest.approx(math.exp(u_plan) / denom)
    assert probs[OUTSIDE_KEY] == pytest.approx(math.exp(u_out) / denom)


def test_missing_prior_prob_defaults_to_zero():
    plans = [_plan("P1")]
    probs = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, {}, OUTSIDE_KEY)
    assert sum(probs.values()) == pytest.approx(1.0)


def test_empty_choice_set_gives_outside_probability_one():
    probs = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", [], {OUTSIDE_KEY: 1.0}, OUTSIDE_KEY)
    assert probs == {OUTSIDE_KEY: pytest.approx(1.0)}


# --- segment shifts probabilities in the documented direction -------------------


def test_price_sensitive_segment_favors_cheap_plan_more_than_mixed():
    cheap = _plan("CHEAP", premium_total=0.0)
    expensive = _plan("EXPENSIVE", premium_total=100.0)
    plans = [cheap, expensive]
    prior = {"CHEAP": 0.3, "EXPENSIVE": 0.3, OUTSIDE_KEY: 0.4}

    mixed_probs = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE_KEY)
    price_probs = utility.choice_probabilities(BASE_COEFFICIENTS, "price_sensitive", plans, prior, OUTSIDE_KEY)

    assert price_probs["CHEAP"] > mixed_probs["CHEAP"]


def test_benefit_maximizer_segment_favors_rich_benefits_plan_more_than_mixed():
    rich = _plan("RICH", has_comprehensive_dental=True, has_vision=True, has_hearing_aids=True, has_otc_or_flex=True)
    bare = _plan("BARE", has_comprehensive_dental=False, has_vision=False, has_hearing_aids=False, has_otc_or_flex=False)
    plans = [rich, bare]
    prior = {"RICH": 0.3, "BARE": 0.3, OUTSIDE_KEY: 0.4}

    mixed_probs = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE_KEY)
    bm_probs = utility.choice_probabilities(BASE_COEFFICIENTS, "benefit_maximizer", plans, prior, OUTSIDE_KEY)

    assert bm_probs["RICH"] > mixed_probs["RICH"]


def test_brand_loyal_segment_amplifies_inertia_gap():
    high_prior_plan = _plan("INCUMBENT")
    low_prior_plan = _plan("CHALLENGER")
    plans = [high_prior_plan, low_prior_plan]
    prior = {"INCUMBENT": 0.7, "CHALLENGER": 0.1, OUTSIDE_KEY: 0.2}

    mixed_probs = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE_KEY)
    loyal_probs = utility.choice_probabilities(BASE_COEFFICIENTS, "brand_loyal", plans, prior, OUTSIDE_KEY)

    # brand_loyal doubles b_inertia, which should widen the gap in favor of
    # the plan already holding most of the prior (status-quo) mass.
    assert (loyal_probs["INCUMBENT"] - loyal_probs["CHALLENGER"]) > (mixed_probs["INCUMBENT"] - mixed_probs["CHALLENGER"])


def test_health_status_driven_segment_favors_high_star_plan_more_than_mixed():
    high_star = _plan("HIGHSTAR", star_rating=5.0)
    low_star = _plan("LOWSTAR", star_rating=2.5)
    plans = [high_star, low_star]
    prior = {"HIGHSTAR": 0.3, "LOWSTAR": 0.3, OUTSIDE_KEY: 0.4}

    mixed_probs = utility.choice_probabilities(BASE_COEFFICIENTS, "mixed", plans, prior, OUTSIDE_KEY)
    hsd_probs = utility.choice_probabilities(BASE_COEFFICIENTS, "health_status_driven", plans, prior, OUTSIDE_KEY)

    assert hsd_probs["HIGHSTAR"] > mixed_probs["HIGHSTAR"]


# --- module purity: no I/O, no globals leaking, plain types only ----------------


def test_module_has_no_side_effect_globals_beyond_documented_constants():
    import inspect

    members = {name: val for name, val in vars(utility).items() if not name.startswith("_") and name != "annotations"}
    functions = {name: val for name, val in members.items() if inspect.isfunction(val)}
    non_functions = {name: val for name, val in members.items() if not inspect.isfunction(val) and not inspect.ismodule(val)}
    # Only plain-data constants (dict/list/str) are allowed as module state.
    for name, val in non_functions.items():
        assert isinstance(val, (dict, list, str, int, float)), f"{name} is not a plain-data constant: {type(val)}"
    assert "choice_probabilities" in functions
    assert "plan_utility" in functions
