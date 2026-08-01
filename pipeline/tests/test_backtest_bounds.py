"""Tests for backtest/bounds.py — Monte Carlo p10/p50/p90 confidence bounds.

Unit tests use small synthetic archetype/plan fixtures (fast, deterministic
given a fixed seed). The real-data integration tests validate the full
80-archetype x ~94-plan run, including the <60s runtime acceptance bar.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pytest

from backtest import bounds
from choice_model import predict
from config.settings import settings

OUTSIDE1 = predict.OUTSIDE_KEY_YEAR1
OUTSIDE2 = predict.OUTSIDE_KEY_YEAR2


def _plan(key, snp_type="Not Applicable", **overrides):
    base = {
        "plan_key": key,
        "snp_type": snp_type,
        "premium_total": 20.0,
        "moop_inn": 5000.0,
        "has_comprehensive_dental": True,
        "has_vision": True,
        "has_hearing_aids": False,
        "has_otc_or_flex": True,
        "star_rating": 4.0,
        "is_ppo": False,
        "enrollment_2025_03": 100.0,
    }
    base.update(overrides)
    return base


def _archetype(id_, weight, prior, dual_proxy=False, age_band="70-74", attitude_segment="mixed"):
    return {
        "id": id_,
        "weight": weight,
        "dual_proxy": dual_proxy,
        "age_band": age_band,
        "attitude_segment": attitude_segment,
        "prior_plan_year1": prior,
    }


def _row(old_c, old_p, new_c, new_p, disposition):
    return {
        "old_contract_id": old_c,
        "old_plan_id": old_p,
        "new_contract_id": new_c,
        "new_plan_id": new_p,
        "disposition": disposition,
    }


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

BOUNDS_FOR_TEST = {
    "b_premium": (-10.0, 0.0),
    "b_moop": (-10.0, 0.0),
    "b_dental": (0.0, 10.0),
    "b_vision_hearing": (0.0, 10.0),
    "b_otc": (0.0, 10.0),
    "b_star": (0.0, 10.0),
    "b_ppo": (-10.0, 10.0),
    "b_inertia": (0.0, 80.0),
    "b_outside": (-20.0, 20.0),
}


# --- jitter_coefficients -------------------------------------------------------------


def test_jitter_coefficients_clips_to_sign_bounds():
    rng = np.random.default_rng(0)
    # b_premium must stay <= 0 even with an enormous forced sd (simulate via
    # a base value near the bound and check many draws never cross it).
    coeffs = {**BASE_COEFFICIENTS, "b_premium": -0.001}
    for _ in range(200):
        jittered = bounds.jitter_coefficients(coeffs, rng, BOUNDS_FOR_TEST)
        assert jittered["b_premium"] <= 0.0
        assert jittered["b_dental"] >= 0.0
        assert jittered["b_inertia"] >= 0.0


def test_jitter_coefficients_deterministic_given_seeded_rng():
    rng_a = np.random.default_rng(42)
    rng_b = np.random.default_rng(42)
    result_a = bounds.jitter_coefficients(BASE_COEFFICIENTS, rng_a, BOUNDS_FOR_TEST)
    result_b = bounds.jitter_coefficients(BASE_COEFFICIENTS, rng_b, BOUNDS_FOR_TEST)
    assert result_a == result_b


def test_jitter_coefficients_min_sd_floor_applies_near_zero():
    # b_star == 0.0 -> sd floor of 0.01 applies (not 0.10*0 == 0), so draws
    # should show real spread, not collapse to exactly 0.0 every time.
    rng = np.random.default_rng(1)
    coeffs = {**BASE_COEFFICIENTS, "b_star": 0.0}
    draws = [bounds.jitter_coefficients(coeffs, rng, BOUNDS_FOR_TEST)["b_star"] for _ in range(50)]
    assert len(set(draws)) > 1


# --- jitter_weights --------------------------------------------------------------------


def test_jitter_weights_preserves_total_population():
    archetypes = [_archetype("a1", 100.0, {}), _archetype("a2", 300.0, {}), _archetype("a3", 50.0, {})]
    rng = np.random.default_rng(7)
    jittered = bounds.jitter_weights(archetypes, rng)
    assert sum(jittered.values()) == pytest.approx(450.0)
    assert set(jittered.keys()) == {"a1", "a2", "a3"}


def test_jitter_weights_all_positive():
    archetypes = [_archetype(f"a{i}", 10.0, {}) for i in range(20)]
    rng = np.random.default_rng(3)
    jittered = bounds.jitter_weights(archetypes, rng)
    assert all(v > 0 for v in jittered.values())


# --- percentile_bounds -----------------------------------------------------------------


def test_percentile_bounds_hand_computed():
    draws = [{"A": 0.1}, {"A": 0.2}, {"A": 0.3}, {"A": 0.4}, {"A": 0.5}]
    result = bounds.percentile_bounds(draws, percentiles=(10, 50, 90))
    assert result["A"]["p50"] == pytest.approx(0.3)
    assert result["A"]["p10"] <= result["A"]["p50"] <= result["A"]["p90"]


def test_percentile_bounds_missing_key_in_some_draws_defaults_to_zero():
    draws = [{"A": 1.0}, {}]
    result = bounds.percentile_bounds(draws, percentiles=(10, 50, 90))
    # values = [0.0, 1.0] -> numpy linear-interpolation p10 = 0.1, p90 = 0.9
    assert result["A"]["p10"] == pytest.approx(np.percentile([0.0, 1.0], 10))
    assert result["A"]["p90"] == pytest.approx(np.percentile([0.0, 1.0], 90))


# --- run_bounds (synthetic, logit) ------------------------------------------------------


def test_run_bounds_logit_returns_p10_le_p50_le_p90_for_every_key():
    plans = [_plan("H0001-A"), _plan("H0001-B")]
    crosswalk_map = predict.crosswalk_map_from_rows(
        [_row("H0001", "A", "H0001", "A", "renewed"), _row("H0001", "B", "H0001", "B", "renewed")]
    )
    archetypes = [
        _archetype("a1", 100.0, {"H0001-A": 0.6, OUTSIDE1: 0.4}),
        _archetype("a2", 200.0, {"H0001-B": 0.5, OUTSIDE1: 0.5}),
    ]
    result = bounds.run_bounds(archetypes, plans, BASE_COEFFICIENTS, crosswalk_map, n_draws=100, seed=42)
    assert set(result.keys()) == {"H0001-A", "H0001-B", OUTSIDE2}
    for key, row in result.items():
        assert row["p10"] <= row["p50"] <= row["p90"]


def test_run_bounds_is_deterministic_given_fixed_seed():
    plans = [_plan("H0001-A")]
    crosswalk_map = predict.crosswalk_map_from_rows([_row("H0001", "A", "H0001", "A", "renewed")])
    archetypes = [_archetype("a1", 100.0, {"H0001-A": 0.6, OUTSIDE1: 0.4})]
    result_a = bounds.run_bounds(archetypes, plans, BASE_COEFFICIENTS, crosswalk_map, n_draws=50, seed=99)
    result_b = bounds.run_bounds(archetypes, plans, BASE_COEFFICIENTS, crosswalk_map, n_draws=50, seed=99)
    assert result_a == result_b


def test_run_bounds_bracket_widens_with_more_draw_variance():
    """Sanity check the bounds aren't degenerate: with real coefficient
    jitter, p90-p10 should be a nonzero spread for a plan with meaningful
    eligible mass."""
    plans = [_plan("H0001-A")]
    crosswalk_map = predict.crosswalk_map_from_rows([_row("H0001", "A", "H0001", "A", "renewed")])
    archetypes = [_archetype("a1", 100.0, {"H0001-A": 0.6, OUTSIDE1: 0.4})]
    result = bounds.run_bounds(archetypes, plans, BASE_COEFFICIENTS, crosswalk_map, n_draws=200, seed=5)
    assert result["H0001-A"]["p90"] > result["H0001-A"]["p10"]


# --- run_bounds with blend_inputs (fixed rank bonus / inertia multiplier) --------------


def test_run_bounds_blended_uses_fixed_persona_inputs_across_draws():
    plans = [_plan("H0001-A"), _plan("H0001-B")]
    crosswalk_map = predict.crosswalk_map_from_rows(
        [_row("H0001", "A", "H0001", "A", "renewed"), _row("H0001", "B", "H0001", "B", "renewed")]
    )
    archetypes = [_archetype("a1", 100.0, {"H0001-A": 0.6, "H0001-B": 0.2, OUTSIDE1: 0.2})]
    blend_inputs = {"a1": {"ranked_plan_keys": ["H0001-B", "H0001-A", OUTSIDE2], "switching_propensity": 0.9}}

    result = bounds.run_bounds(
        archetypes, plans, BASE_COEFFICIENTS, crosswalk_map, n_draws=100, seed=11, blend_inputs=blend_inputs
    )
    assert set(result.keys()) == {"H0001-A", "H0001-B", OUTSIDE2}
    for row in result.values():
        assert row["p10"] <= row["p50"] <= row["p90"]


# --- real-data integration ---------------------------------------------------------------


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
def test_real_run_bounds_contains_point_estimate_small_n():
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    archetypes, plans_2025, coefficients, crosswalk_map = _load_real()
    base_coefficients = coefficients["base_coefficients"]

    point = predict.predict_all(archetypes, plans_2025, base_coefficients, crosswalk_map)["aggregate_shares"]
    result = bounds.run_bounds(archetypes, plans_2025, base_coefficients, crosswalk_map, n_draws=60, seed=settings.SEED)

    assert set(result.keys()) == set(point.keys())
    n_violations = sum(1 for key in point if not (result[key]["p10"] <= point[key] <= result[key]["p90"]))
    # allow a small tolerance: the point estimate uses the UNJITTERED
    # coefficients, so it should almost always fall inside its own draws'
    # p10-p90 band, but a handful of tiny-mass plans near a hard boundary
    # (e.g. clipped coefficient sign bounds) may occasionally miss.
    assert n_violations <= 2, f"{n_violations} plans had point estimate outside [p10, p90]"


@pytest.mark.integration
def test_real_run_bounds_full_n_completes_under_60s():
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    archetypes, plans_2025, coefficients, crosswalk_map = _load_real()
    base_coefficients = coefficients["base_coefficients"]

    start = time.monotonic()
    result = bounds.run_bounds(
        archetypes, plans_2025, base_coefficients, crosswalk_map, n_draws=bounds.N_DRAWS_DEFAULT, seed=settings.SEED
    )
    elapsed = time.monotonic() - start

    assert len(result) == 95  # 94 plans + outside
    assert elapsed < 60.0, f"bounds.run_bounds(N=1000) took {elapsed:.1f}s (must be < 60s)"
