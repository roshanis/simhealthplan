"""Tests for choice_model/calibrate.py — Year-1 multinomial-logit calibration.

Unit tests exercise the pure computation helpers (vector<->dict, predicted
counts, loss function, fit metrics) against small synthetic archetype/plan
fixtures. The full ``calibrate()``/``build()`` run (multi-start L-BFGS-B
over the real 80 archetypes x 93 plans) is an integration test marked
``pytest.mark.integration`` -- this is the master acceptance test for the
Phase 3 Year-1 fit quality bar (size-weighted MAE <= 0.30pp, outside share
within 2pp of actual).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from choice_model import calibrate, choice_sets, utility
from choice_model.schemas import CoefficientsFile
from config.settings import settings

OUTSIDE_KEY = "other_or_no_ma_2024"


# --- vector <-> dict roundtrip -----------------------------------------------


def test_coefficients_vector_roundtrip():
    coeffs = {name: float(i) for i, name in enumerate(utility.BASE_COEFFICIENT_NAMES)}
    vec = calibrate.coefficients_to_vector(coeffs)
    assert isinstance(vec, np.ndarray)
    back = calibrate.vector_to_coefficients(vec)
    assert back == pytest.approx(coeffs)


def test_bounds_vector_matches_names_order():
    bounds = calibrate.bounds_vector()
    assert len(bounds) == len(utility.BASE_COEFFICIENT_NAMES)
    # sign sanity per spec: b_premium/b_moop <= 0; benefits/star/inertia >= 0
    by_name = dict(zip(utility.BASE_COEFFICIENT_NAMES, bounds))
    assert by_name["b_premium"][1] <= 0
    assert by_name["b_moop"][1] <= 0
    assert by_name["b_dental"][0] >= 0
    assert by_name["b_vision_hearing"][0] >= 0
    assert by_name["b_otc"][0] >= 0
    assert by_name["b_star"][0] >= 0
    assert by_name["b_inertia"][0] >= 0


# --- small synthetic fixtures -------------------------------------------------


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
        "enrollment_2024_03": 100.0,
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


@pytest.fixture
def small_plans():
    return [
        _plan("A", premium_total=0.0, enrollment_2024_03=300.0),
        _plan("B", premium_total=50.0, enrollment_2024_03=100.0),
    ]


@pytest.fixture
def small_archetypes():
    return [
        _archetype("arch1", 1000.0, {"A": 0.6, "B": 0.2, OUTSIDE_KEY: 0.2}),
        _archetype("arch2", 500.0, {"A": 0.3, "B": 0.5, OUTSIDE_KEY: 0.2}),
    ]


# --- prepare_archetype_choice_data --------------------------------------------


def test_prepare_archetype_choice_data_shapes(small_archetypes, small_plans):
    prepared = calibrate.prepare_archetype_choice_data(small_archetypes, small_plans, OUTSIDE_KEY)
    assert len(prepared) == 2
    for entry in prepared:
        assert set(entry.keys()) == {"id", "weight", "segment", "eligible_plans", "renormalized_prior"}
        assert sum(entry["renormalized_prior"].values()) == pytest.approx(1.0)


def test_prepare_archetype_choice_data_excludes_ineligible_dsnp(small_plans):
    dsnp_plan = _plan("DSNP", snp_type="Dual-Eligible", enrollment_2024_03=50.0)
    plans = small_plans + [dsnp_plan]
    archetypes = [_archetype("nondual", 100.0, {"A": 0.5, "DSNP": 0.3, OUTSIDE_KEY: 0.2}, dual_proxy=False)]
    prepared = calibrate.prepare_archetype_choice_data(archetypes, plans, OUTSIDE_KEY)
    eligible_keys = {p["plan_key"] for p in prepared[0]["eligible_plans"]}
    assert "DSNP" not in eligible_keys
    assert prepared[0]["renormalized_prior"]["DSNP"] == 0.0


# --- actual_2024_targets ------------------------------------------------------


def test_actual_2024_targets_outside_is_residual(small_plans):
    targets = calibrate.actual_2024_targets(small_plans, eligibles_total=1000.0, outside_key=OUTSIDE_KEY)
    assert targets["A"] == pytest.approx(300.0)
    assert targets["B"] == pytest.approx(100.0)
    assert targets[OUTSIDE_KEY] == pytest.approx(1000.0 - 400.0)


# --- predicted_2024_counts / loss ---------------------------------------------


def test_predicted_2024_counts_sums_to_eligibles_total(small_archetypes, small_plans):
    prepared = calibrate.prepare_archetype_choice_data(small_archetypes, small_plans, OUTSIDE_KEY)
    coeffs = {name: 0.0 for name in utility.BASE_COEFFICIENT_NAMES}
    coeffs["b_inertia"] = 2.0
    predicted = calibrate.predicted_2024_counts(coeffs, prepared, small_plans, OUTSIDE_KEY)
    total_weight = sum(a["weight"] for a in small_archetypes)
    assert sum(predicted.values()) == pytest.approx(total_weight)


def test_loss_function_zero_when_prediction_matches_actual_exactly():
    # Degenerate single-archetype-single-plan case where prediction can be
    # made to exactly match the target: one plan holding 100% of the
    # archetype's weight, no outside share.
    plans = [_plan("ONLY", enrollment_2024_03=1000.0)]
    archetypes = [_archetype("a1", 1000.0, {"ONLY": 1.0, OUTSIDE_KEY: 0.0})]
    prepared = calibrate.prepare_archetype_choice_data(archetypes, plans, OUTSIDE_KEY)
    actual = calibrate.actual_2024_targets(plans, eligibles_total=1000.0, outside_key=OUTSIDE_KEY)

    # b_inertia very large, prior_prob("ONLY")=1.0 vs outside=0.0 -> softmax -> ~all mass on ONLY
    coeffs = {name: 0.0 for name in utility.BASE_COEFFICIENT_NAMES}
    coeffs["b_inertia"] = 50.0
    x = calibrate.coefficients_to_vector(coeffs)
    prior_vector = x.copy()
    loss = calibrate.loss_function(x, prepared, plans, actual, 1000.0, prior_vector, l2_lambda=0.0, outside_key=OUTSIDE_KEY)
    assert loss < 1e-6


def test_loss_function_l2_penalty_increases_loss_away_from_prior():
    plans = [_plan("A", enrollment_2024_03=500.0)]
    archetypes = [_archetype("a1", 1000.0, {"A": 0.5, OUTSIDE_KEY: 0.5})]
    prepared = calibrate.prepare_archetype_choice_data(archetypes, plans, OUTSIDE_KEY)
    actual = calibrate.actual_2024_targets(plans, eligibles_total=1000.0, outside_key=OUTSIDE_KEY)

    prior_vector = calibrate.coefficients_to_vector({name: 0.0 for name in utility.BASE_COEFFICIENT_NAMES})
    x_at_prior = prior_vector.copy()
    x_away = prior_vector.copy()
    x_away[0] = -5.0  # b_premium far from its 0.0 prior

    loss_at_prior = calibrate.loss_function(x_at_prior, prepared, plans, actual, 1000.0, prior_vector, l2_lambda=1.0, outside_key=OUTSIDE_KEY)
    loss_away = calibrate.loss_function(x_away, prepared, plans, actual, 1000.0, prior_vector, l2_lambda=1.0, outside_key=OUTSIDE_KEY)
    assert loss_away > loss_at_prior


# --- compute_fit_metrics -------------------------------------------------------


def test_compute_fit_metrics_perfect_fit_is_near_zero_mae():
    plans = [_plan("ONLY", enrollment_2024_03=1000.0)]
    archetypes = [_archetype("a1", 1000.0, {"ONLY": 1.0, OUTSIDE_KEY: 0.0})]
    prepared = calibrate.prepare_archetype_choice_data(archetypes, plans, OUTSIDE_KEY)
    actual = calibrate.actual_2024_targets(plans, eligibles_total=1000.0, outside_key=OUTSIDE_KEY)

    coeffs = {name: 0.0 for name in utility.BASE_COEFFICIENT_NAMES}
    coeffs["b_inertia"] = 50.0
    metrics = calibrate.compute_fit_metrics(coeffs, prepared, plans, actual, 1000.0, OUTSIDE_KEY)
    assert metrics["size_weighted_mae_pp"] < 0.01
    assert metrics["outside_share_error_pp"] < 0.01


def test_compute_fit_metrics_worst_5_sorted_descending(small_archetypes, small_plans):
    prepared = calibrate.prepare_archetype_choice_data(small_archetypes, small_plans, OUTSIDE_KEY)
    actual = calibrate.actual_2024_targets(small_plans, eligibles_total=1500.0, outside_key=OUTSIDE_KEY)
    coeffs = {name: 0.0 for name in utility.BASE_COEFFICIENT_NAMES}
    metrics = calibrate.compute_fit_metrics(coeffs, prepared, small_plans, actual, 1500.0, OUTSIDE_KEY)
    errors = [row["abs_error_pp"] for row in metrics["worst_5_plans_by_abs_error"]]
    assert errors == sorted(errors, reverse=True)
    assert metrics["n_plans"] == 2


# --- fit_coefficients (small synthetic optimizer smoke test) -------------------


def test_fit_coefficients_is_deterministic_given_seed(small_archetypes, small_plans):
    prepared = calibrate.prepare_archetype_choice_data(small_archetypes, small_plans, OUTSIDE_KEY)
    actual = calibrate.actual_2024_targets(small_plans, eligibles_total=1500.0, outside_key=OUTSIDE_KEY)

    result1 = calibrate.fit_coefficients(prepared, small_plans, actual, 1500.0, seed=42, max_iter=100)
    result2 = calibrate.fit_coefficients(prepared, small_plans, actual, 1500.0, seed=42, max_iter=100)
    assert result1["coefficients"] == pytest.approx(result2["coefficients"])
    assert result1["final_loss"] == pytest.approx(result2["final_loss"])


def test_fit_coefficients_respects_bounds(small_archetypes, small_plans):
    prepared = calibrate.prepare_archetype_choice_data(small_archetypes, small_plans, OUTSIDE_KEY)
    actual = calibrate.actual_2024_targets(small_plans, eligibles_total=1500.0, outside_key=OUTSIDE_KEY)
    result = calibrate.fit_coefficients(prepared, small_plans, actual, 1500.0, seed=42, max_iter=200)
    coeffs = result["coefficients"]
    bounds = dict(zip(utility.BASE_COEFFICIENT_NAMES, calibrate.bounds_vector()))
    for name, value in coeffs.items():
        lo, hi = bounds[name]
        assert lo - 1e-9 <= value <= hi + 1e-9


def test_fit_coefficients_returns_n_starts_records(small_archetypes, small_plans):
    prepared = calibrate.prepare_archetype_choice_data(small_archetypes, small_plans, OUTSIDE_KEY)
    actual = calibrate.actual_2024_targets(small_plans, eligibles_total=1500.0, outside_key=OUTSIDE_KEY)
    result = calibrate.fit_coefficients(prepared, small_plans, actual, 1500.0, seed=42, n_starts=3, max_iter=50)
    assert len(result["per_start"]) == 3
    assert result["best_start_index"] in (0, 1, 2)
    assert result["final_loss"] == min(r["final_loss"] for r in result["per_start"])


# --- integration: real data (master Phase 3 acceptance test) -------------------


def _real_data_available() -> bool:
    return (settings.PROCESSED_DIR / "archetypes.json").exists() and (settings.PROCESSED_DIR / f"plans_{settings.YEAR1}.json").exists()


@pytest.fixture(scope="module")
def real_result():
    if not _real_data_available():
        pytest.skip("archetypes.json / plans_2024.json not present; run `make archetypes calibrate` first")
    return calibrate.calibrate()


@pytest.mark.integration
def test_real_y1_size_weighted_mae_within_threshold(real_result):
    mae = real_result["metadata"]["fit_metrics_year1"]["size_weighted_mae_pp"]
    assert mae <= 0.30


@pytest.mark.integration
def test_real_outside_share_within_2pp(real_result):
    err = real_result["metadata"]["fit_metrics_year1"]["outside_share_error_pp"]
    assert err <= 2.0


@pytest.mark.integration
def test_real_coefficient_signs_match_bounds(real_result):
    coeffs = real_result["base_coefficients"]
    assert coeffs["b_premium"] <= 0
    assert coeffs["b_moop"] <= 0
    assert coeffs["b_dental"] >= 0
    assert coeffs["b_vision_hearing"] >= 0
    assert coeffs["b_otc"] >= 0
    assert coeffs["b_star"] >= 0
    assert coeffs["b_inertia"] >= 0


@pytest.mark.integration
def test_real_schema_validates(real_result):
    CoefficientsFile.model_validate(real_result)


@pytest.mark.integration
def test_real_probabilities_sum_to_one_for_every_archetype(real_result):
    archetypes = calibrate._load_archetypes()
    _, plans = calibrate._load_plans_2024()
    prepared = calibrate.prepare_archetype_choice_data(archetypes, plans, OUTSIDE_KEY)
    coeffs = real_result["base_coefficients"]
    for entry in prepared:
        probs = utility.choice_probabilities(coeffs, entry["segment"], entry["eligible_plans"], entry["renormalized_prior"], OUTSIDE_KEY)
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.integration
def test_real_deterministic_build_is_byte_identical(tmp_path):
    if not _real_data_available():
        pytest.skip("archetypes.json / plans_2024.json not present; run `make archetypes calibrate` first")
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    calibrate.build(output_path=path_a)
    calibrate.build(output_path=path_b)
    assert path_a.read_bytes() == path_b.read_bytes()


@pytest.mark.integration
def test_real_output_file_written():
    if not _real_data_available():
        pytest.skip("archetypes.json / plans_2024.json not present; run `make archetypes calibrate` first")
    calibrate.build()
    path = settings.PROCESSED_DIR / "coefficients.json"
    assert path.exists()
    on_disk = json.loads(path.read_text())
    assert "base_coefficients" in on_disk
    assert "metadata" in on_disk
