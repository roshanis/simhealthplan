"""Tests for backtest/diagnostics.py — pure post-hoc diagnostics functions.

Hand-computable tiny fixtures only for the pure functions (mirrors
test_backtest_metrics.py's convention). The one real-data test
(``test_real_backtest_result_self_check_parity``) is the REQUIRED parity
self-check against the committed ``data/processed/backtest_result.json``
artifact -- marked ``@pytest.mark.integration`` and skipped cleanly if that
artifact isn't present (this environment cannot regenerate it; CMS access is
blocked -- see diagnostics.py's module docstring).
"""

from __future__ import annotations

import pytest

from backtest import diagnostics
from config.settings import settings

OUTSIDE = "other_or_no_ma_2025"


# =============================================================================
# Shared extraction helpers
# =============================================================================


def test_build_score_inputs_skips_none_valued_variant():
    per_plan = [
        {
            "plan_key": "A",
            "share_2025_pred_logit": 0.3,
            "share_2025_actual": 0.25,
            "enrollment_2024": 10.0,
        },
        {
            "plan_key": "B",
            "share_2025_pred_logit": None,
            "share_2025_actual": 0.5,
            "enrollment_2024": 20.0,
        },
    ]
    predicted, actual, weights = diagnostics.build_score_inputs(
        per_plan, "share_2025_pred_logit"
    )
    assert predicted == {
        "A": 0.3
    }  # "B" skipped -- variant not computed for it, not coerced to 0.0
    assert actual == {"A": 0.25, "B": 0.5}
    assert weights == {"A": 10.0, "B": 20.0}


def test_plan_level_keys_excludes_outside_and_sorts():
    per_plan = [{"plan_key": "B"}, {"plan_key": OUTSIDE}, {"plan_key": "A"}]
    assert diagnostics.plan_level_keys(per_plan, outside_key=OUTSIDE) == ["A", "B"]


def test_self_check_weighted_mae_logit_passes_on_hand_computed_value():
    per_plan = [
        {
            "plan_key": "A",
            "share_2025_pred_logit": 0.30,
            "share_2025_actual": 0.25,
            "enrollment_2024": 10.0,
        },
        {
            "plan_key": "B",
            "share_2025_pred_logit": 0.50,
            "share_2025_actual": 0.50,
            "enrollment_2024": 20.0,
        },
        {
            "plan_key": OUTSIDE,
            "share_2025_pred_logit": 0.20,
            "share_2025_actual": 0.25,
            "enrollment_2024": 999.0,
        },
    ]
    # outside excluded -> only A (err=0.05, w=10) and B (err=0.0, w=20): (10*0.05 + 20*0.0) / 30
    published = (10.0 * 0.05 + 20.0 * 0.0) / 30.0
    result = diagnostics.self_check_weighted_mae_logit(per_plan, published)
    assert result == pytest.approx(published)


def test_self_check_weighted_mae_logit_raises_on_mismatch():
    per_plan = [
        {
            "plan_key": "A",
            "share_2025_pred_logit": 0.30,
            "share_2025_actual": 0.25,
            "enrollment_2024": 10.0,
        },
        {
            "plan_key": OUTSIDE,
            "share_2025_pred_logit": 0.20,
            "share_2025_actual": 0.25,
            "enrollment_2024": 999.0,
        },
    ]
    with pytest.raises(AssertionError):
        diagnostics.self_check_weighted_mae_logit(per_plan, published_value=0.5)


# =============================================================================
# A. Confidence-bound coverage
# =============================================================================


def test_coverage_stats_boundary_inclusive_and_classification():
    # A: squarely inside -> covered. B: strictly below p10 -> below.
    # C: strictly above p90 -> above. D: EXACTLY at p10 -> covered (inclusive).
    actual = {"A": 0.5, "B": 0.05, "C": 0.95, "D": 0.1}
    bounds = {
        "A": {"p10": 0.4, "p50": 0.5, "p90": 0.6},
        "B": {"p10": 0.1, "p50": 0.2, "p90": 0.3},
        "C": {"p10": 0.5, "p50": 0.6, "p90": 0.9},
        "D": {"p10": 0.1, "p50": 0.15, "p90": 0.2},
    }
    weights = {"A": 10.0, "B": 20.0, "C": 30.0, "D": 40.0}
    result = diagnostics.coverage_stats(
        actual, bounds, weights, keys=["A", "B", "C", "D"]
    )

    assert result["n_evaluated"] == 4
    assert result["n_covered"] == 2
    assert result["n_below"] == 1
    assert result["n_above"] == 1
    assert result["covered_keys"] == ["A", "D"]
    assert result["below_keys"] == ["B"]
    assert result["above_keys"] == ["C"]
    assert result["unweighted_coverage"] == pytest.approx(0.5)
    # weighted: covered weight = 10 (A) + 40 (D) = 50; total = 10+20+30+40 = 100
    assert result["weighted_coverage"] == pytest.approx(0.5)


def test_coverage_stats_skips_keys_missing_from_bounds_or_actual():
    actual = {"A": 0.5}
    bounds = {"A": {"p10": 0.4, "p50": 0.5, "p90": 0.6}}
    weights = {"A": 10.0}
    result = diagnostics.coverage_stats(actual, bounds, weights, keys=["A", "E"])
    assert result["n_evaluated"] == 1
    assert result["skipped_missing_bounds_or_actual"] == ["E"]


def test_coverage_stats_empty_returns_none_rates():
    result = diagnostics.coverage_stats({}, {}, {}, keys=[])
    assert result["n_evaluated"] == 0
    assert result["unweighted_coverage"] is None
    assert result["weighted_coverage"] is None


def test_calibration_verdict_well_calibrated_inclusive_of_tolerance_boundary():
    assert diagnostics.calibration_verdict(0.80) == "well_calibrated"
    assert (
        diagnostics.calibration_verdict(0.75) == "well_calibrated"
    )  # exactly nominal - tolerance
    assert (
        diagnostics.calibration_verdict(0.85) == "well_calibrated"
    )  # exactly nominal + tolerance


def test_calibration_verdict_too_narrow_overconfident():
    assert diagnostics.calibration_verdict(0.18) == "too_narrow_overconfident"
    assert diagnostics.calibration_verdict(0.7499) == "too_narrow_overconfident"


def test_calibration_verdict_too_wide_overconservative():
    assert diagnostics.calibration_verdict(0.99) == "too_wide_overconservative"
    assert diagnostics.calibration_verdict(0.8501) == "too_wide_overconservative"


def test_calibration_verdict_not_computable_on_none():
    assert diagnostics.calibration_verdict(None) == "not_computable"


def test_reconcile_bounds_coverage_reports_set_differences_explicitly():
    per_plan = [{"plan_key": "A"}, {"plan_key": "B"}, {"plan_key": OUTSIDE}]
    bounds = {
        "A": {},
        "B": {},
        "Z": {},
    }  # missing OUTSIDE, has an extra "Z" not in per_plan
    result = diagnostics.reconcile_bounds_coverage(
        per_plan, bounds, outside_key=OUTSIDE
    )
    assert result["n_per_plan_rows_total"] == 3
    assert result["n_per_plan_rows_plan_level"] == 2
    assert result["n_bounds_entries_total"] == 3
    assert (
        result["n_bounds_entries_plan_level"] == 3
    )  # "Z" isn't the outside key, so it's not subtracted
    assert result["keys_in_per_plan_not_in_bounds"] == [OUTSIDE]
    assert result["keys_in_bounds_not_in_per_plan"] == ["Z"]
    assert result["outside_key_present_in_bounds"] is False


def test_reconcile_bounds_coverage_no_mismatch_case():
    per_plan = [{"plan_key": "A"}, {"plan_key": OUTSIDE}]
    bounds = {"A": {}, OUTSIDE: {}}
    result = diagnostics.reconcile_bounds_coverage(
        per_plan, bounds, outside_key=OUTSIDE
    )
    assert result["keys_in_per_plan_not_in_bounds"] == []
    assert result["keys_in_bounds_not_in_per_plan"] == []
    assert result["outside_key_present_in_bounds"] is True


# =============================================================================
# B. Shrinkage / damping blend
# =============================================================================


def test_damped_share_prediction_lambda_zero_reduces_exactly_to_naive():
    pred_logit = {"A": 0.7, "B": 0.3}
    pred_naive = {"A": 0.4, "B": 0.6}
    result = diagnostics.damped_share_prediction(pred_logit, pred_naive, 0.0)
    assert result["A"] == pytest.approx(0.4)
    assert result["B"] == pytest.approx(0.6)


def test_damped_share_prediction_lambda_one_reduces_exactly_to_logit():
    pred_logit = {"A": 0.7, "B": 0.3}
    pred_naive = {"A": 0.4, "B": 0.6}
    result = diagnostics.damped_share_prediction(pred_logit, pred_naive, 1.0)
    assert result["A"] == pytest.approx(0.7)
    assert result["B"] == pytest.approx(0.3)


def test_damped_share_prediction_renormalizes_non_unit_sum_inputs():
    # Neither input sums to 1.0 here -- the defensive renormalization step
    # should still be exercised (raw sums to 3.0, not 1.0).
    pred_logit = {"A": 1.0, "B": 1.0}  # sums to 2.0
    pred_naive = {"A": 1.0, "B": 3.0}  # sums to 4.0
    result = diagnostics.damped_share_prediction(pred_logit, pred_naive, 0.5)
    # raw = {"A": 0.5*1 + 0.5*1 = 1.0, "B": 0.5*1 + 0.5*3 = 2.0}, raw sum = 3.0
    assert result["A"] == pytest.approx(1.0 / 3.0)
    assert result["B"] == pytest.approx(2.0 / 3.0)


def test_sweep_lambda_hand_computed_weighted_mae_and_directional_accuracy():
    pred_logit = {"A": 0.6, "B": 0.4}
    pred_naive = {"A": 0.3, "B": 0.7}
    actual = {"A": 0.5, "B": 0.5}
    share_2024 = {
        "A": 0.3,
        "B": 0.7,
    }  # equals naive, so naive's shift is exactly 0 at both plans
    weights = {"A": 2.0, "B": 2.0}

    rows = diagnostics.sweep_lambda(
        pred_logit, pred_naive, actual, share_2024, weights, [0.0, 0.5, 1.0], ["A", "B"]
    )
    by_lambda = {row["lambda"]: row for row in rows}

    # lambda=0.0 -> pure naive: errors 0.2, 0.2 -> wmae = (2*0.2+2*0.2)/4 = 0.2
    assert by_lambda[0.0]["weighted_mae"] == pytest.approx(0.2)
    # predicted shift is 0/0 at both plans (naive == share_2024) while actual shift is nonzero at both
    # -> both count as mismatches (0 vs nonzero) -> directional accuracy 0/2
    assert by_lambda[0.0]["directional_accuracy"] == pytest.approx(0.0)

    # lambda=1.0 -> pure logit: errors 0.1, 0.1 -> wmae = (2*0.1+2*0.1)/4 = 0.1
    assert by_lambda[1.0]["weighted_mae"] == pytest.approx(0.1)
    # predicted shift signs (+0.3, -0.3) match actual shift signs (+0.2, -0.2) -> 2/2
    assert by_lambda[1.0]["directional_accuracy"] == pytest.approx(1.0)

    # lambda=0.5 -> damped = {"A": 0.45, "B": 0.55}: errors 0.05, 0.05 -> wmae = (2*0.05+2*0.05)/4 = 0.05
    assert by_lambda[0.5]["weighted_mae"] == pytest.approx(0.05)
    assert by_lambda[0.5]["directional_accuracy"] == pytest.approx(1.0)


def test_select_oracle_lambda_picks_lowest_mae_breaking_ties_toward_smaller_lambda():
    rows = [
        {"lambda": 0.0, "weighted_mae": 0.05, "directional_accuracy": 0.5},
        {
            "lambda": 0.5,
            "weighted_mae": 0.05,
            "directional_accuracy": 0.9,
        },  # tied MAE, worse tie-break rank
        {"lambda": 1.0, "weighted_mae": 0.10, "directional_accuracy": 1.0},
    ]
    result = diagnostics.select_oracle_lambda(rows)
    assert result["lambda"] == 0.0


def test_select_oracle_lambda_raises_on_empty_sweep():
    with pytest.raises(ValueError):
        diagnostics.select_oracle_lambda([])


def test_leave_one_plan_out_cv_hand_computed_two_plan_case():
    # naive strictly dominates logit for both plans under leave-one-out
    # scoring, so both folds should pick lambda=0.0.
    pred_logit = {"A": 0.7, "B": 0.3}
    pred_naive = {"A": 0.4, "B": 0.6}
    actual = {"A": 0.5, "B": 0.5}
    share_2024 = {"A": 0.4, "B": 0.6}  # equals naive
    weights = {"A": 1.0, "B": 3.0}

    result = diagnostics.leave_one_plan_out_cv(
        ["A", "B"], pred_logit, pred_naive, actual, share_2024, weights, [0.0, 1.0]
    )

    assert result["chosen_lambda_by_plan"] == {"A": 0.0, "B": 0.0}
    # fold_predicted == naive exactly (both folds pick lambda=0.0)
    # weighted_mae = (1*|0.4-0.5| + 3*|0.6-0.5|) / (1+3) = (0.1 + 0.3) / 4 = 0.1
    assert result["weighted_mae"] == pytest.approx(0.1)
    # predicted shift is 0/0 (== naive == share_2024) at both plans, actual shift is nonzero at both
    # -> both mismatches -> directional accuracy 0.0
    assert result["directional_accuracy"] == pytest.approx(0.0)
    assert result["n_plans"] == 2


def test_leave_one_plan_out_cv_respects_always_exclude():
    # Same shape as the hand-computed two-plan case above, but with an
    # outside-option key present in every dict (and part of the same
    # sum-to-1.0 distribution, matching the real pipeline's convention) --
    # always_exclude must keep "OUT" out of every fold's weighted_mae call
    # (both from the numerator and the fold's own weight total).
    pred_logit = {"A": 0.35, "B": 0.15, "OUT": 0.5}
    pred_naive = {"A": 0.20, "B": 0.30, "OUT": 0.5}
    actual = {"A": 0.25, "B": 0.25, "OUT": 0.5}
    share_2024 = {"A": 0.20, "B": 0.30, "OUT": 0.5}  # equals naive
    weights = {"A": 1.0, "B": 3.0, "OUT": 10_000.0}

    result = diagnostics.leave_one_plan_out_cv(
        ["A", "B"],
        pred_logit,
        pred_naive,
        actual,
        share_2024,
        weights,
        [0.0, 1.0],
        always_exclude={"OUT"},
    )
    assert result["chosen_lambda_by_plan"] == {"A": 0.0, "B": 0.0}
    # fold_predicted == naive exactly (both folds pick lambda=0.0):
    # weighted_mae = (1*|0.20-0.25| + 3*|0.30-0.25|) / (1+3) = (0.05 + 0.15) / 4 = 0.05
    # "OUT"'s enormous weight (10_000) must NOT leak into this -- always_exclude keeps it out entirely.
    assert result["weighted_mae"] == pytest.approx(0.05)


def test_lambda_distribution_hand_computed():
    result = diagnostics.lambda_distribution({"A": 0.0, "B": 0.0, "C": 0.5})
    assert result["n"] == 3
    assert result["mean"] == pytest.approx((0.0 + 0.0 + 0.5) / 3.0)
    assert result["min"] == pytest.approx(0.0)
    assert result["max"] == pytest.approx(0.5)
    assert result["counts"] == {"0.00": 2, "0.50": 1}


def test_lambda_distribution_empty():
    result = diagnostics.lambda_distribution({})
    assert result == {"n": 0, "mean": None, "min": None, "max": None, "counts": {}}


# =============================================================================
# C. Per-plan error decomposition
# =============================================================================


def test_error_contributions_sums_to_weighted_mae_and_ranks_descending():
    predicted = {"A": 0.30, "B": 0.50, "C": 0.20}
    actual = {"A": 0.25, "B": 0.60, "C": 0.15}
    weights = {"A": 10.0, "B": 20.0, "C": 70.0}
    # errors: A=0.05, B=0.10, C=0.05; total_weight=100
    # contributions: A=10/100*0.05=0.005, B=20/100*0.10=0.02, C=70/100*0.05=0.035
    rows = diagnostics.error_contributions(predicted, actual, weights)
    by_key = {row["plan_key"]: row for row in rows}
    assert by_key["A"]["contribution"] == pytest.approx(0.005)
    assert by_key["B"]["contribution"] == pytest.approx(0.02)
    assert by_key["C"]["contribution"] == pytest.approx(0.035)

    # descending order: C, B, A
    assert [row["plan_key"] for row in rows] == ["C", "B", "A"]

    # sum of contributions == metrics.weighted_mae on the same inputs
    from backtest import metrics

    total_contribution = sum(row["contribution"] for row in rows)
    expected_mae = metrics.weighted_mae(predicted, actual, weights)
    assert total_contribution == pytest.approx(expected_mae)


def test_error_contributions_respects_exclude_keys():
    predicted = {"A": 0.30, "OUT": 0.9}
    actual = {"A": 0.25, "OUT": 0.5}
    weights = {"A": 10.0, "OUT": 1000.0}
    rows = diagnostics.error_contributions(
        predicted, actual, weights, exclude_keys={"OUT"}
    )
    assert [row["plan_key"] for row in rows] == ["A"]
    assert rows[0]["contribution"] == pytest.approx(
        0.05
    )  # sole plan -> its full weight share


def test_with_cumulative_share_hand_computed():
    rows = diagnostics.error_contributions(
        {"A": 0.30, "B": 0.50, "C": 0.20},
        {"A": 0.25, "B": 0.60, "C": 0.15},
        {"A": 10.0, "B": 20.0, "C": 70.0},
    )
    result = diagnostics.with_cumulative_share(rows)
    # order is C (0.035), B (0.02), A (0.005); total = 0.06
    assert result[0]["plan_key"] == "C"
    assert result[0]["cumulative_share_of_total"] == pytest.approx(0.035 / 0.06)
    assert result[1]["cumulative_share_of_total"] == pytest.approx(0.055 / 0.06)
    assert result[2]["cumulative_share_of_total"] == pytest.approx(1.0)


def test_plans_to_reach_cumulative_share_hand_computed():
    rows = diagnostics.error_contributions(
        {"A": 0.30, "B": 0.50, "C": 0.20},
        {"A": 0.25, "B": 0.60, "C": 0.15},
        {"A": 10.0, "B": 20.0, "C": 70.0},
    )
    with_cum = diagnostics.with_cumulative_share(rows)
    # cumulative shares: C=0.5833, B=0.9167, A=1.0
    assert diagnostics.plans_to_reach_cumulative_share(with_cum, 0.50) == 1
    assert diagnostics.plans_to_reach_cumulative_share(with_cum, 0.90) == 2
    assert diagnostics.plans_to_reach_cumulative_share(with_cum, 0.99) == 3


def test_plans_to_reach_cumulative_share_unreachable_target_returns_full_length():
    rows = diagnostics.error_contributions({"A": 0.3}, {"A": 0.25}, {"A": 10.0})
    with_cum = diagnostics.with_cumulative_share(rows)
    assert diagnostics.plans_to_reach_cumulative_share(with_cum, 5.0) == len(with_cum)


def test_split_new_entrants_vs_incumbents_hand_computed():
    per_plan = [
        {
            "plan_key": "A",
            "enrollment_2024": 0.0,
            "share_2025_pred_logit": 0.02,
            "share_2025_actual": 0.05,
        },
        {
            "plan_key": "B",
            "enrollment_2024": 100.0,
            "share_2025_pred_logit": 0.10,
            "share_2025_actual": 0.08,
        },
        {
            "plan_key": "C",
            "enrollment_2024": 50.0,
            "share_2025_pred_logit": 0.20,
            "share_2025_actual": 0.25,
        },
        {
            "plan_key": OUTSIDE,
            "enrollment_2024": 9999.0,
            "share_2025_pred_logit": 0.5,
            "share_2025_actual": 0.5,
        },
    ]
    result = diagnostics.split_new_entrants_vs_incumbents(
        per_plan, "share_2025_pred_logit", outside_key=OUTSIDE
    )

    assert result["new_entrants"]["n_plans"] == 1
    assert result["new_entrants"]["unweighted_mean_abs_error"] == pytest.approx(0.03)
    assert result["new_entrants"]["total_enrollment_2024"] == pytest.approx(0.0)

    assert result["incumbents"]["n_plans"] == 2
    assert result["incumbents"]["unweighted_mean_abs_error"] == pytest.approx(
        (0.02 + 0.05) / 2.0
    )
    assert result["incumbents"]["total_enrollment_2024"] == pytest.approx(150.0)


def test_split_new_entrants_vs_incumbents_empty_group():
    per_plan = [
        {
            "plan_key": "A",
            "enrollment_2024": 100.0,
            "share_2025_pred_logit": 0.1,
            "share_2025_actual": 0.1,
        }
    ]
    result = diagnostics.split_new_entrants_vs_incumbents(
        per_plan, "share_2025_pred_logit", outside_key=OUTSIDE
    )
    assert result["new_entrants"] == {
        "n_plans": 0,
        "unweighted_mean_abs_error": None,
        "total_enrollment_2024": 0.0,
    }


def test_org_rollup_aggregates_and_sorts_descending():
    contributions = diagnostics.error_contributions(
        {"A": 0.30, "B": 0.50, "C": 0.20},
        {"A": 0.25, "B": 0.60, "C": 0.15},
        {"A": 10.0, "B": 20.0, "C": 70.0},
    )
    per_plan_by_key = {
        "A": {"org": "OrgX"},
        "B": {"org": "OrgY"},
        "C": {"org": "OrgX"},  # OrgX gets both A (0.005) and C (0.035) -> 0.04 total
    }
    rollup = diagnostics.org_rollup(contributions, per_plan_by_key)
    by_org = {row["org"]: row for row in rollup}
    assert by_org["OrgX"]["n_plans"] == 2
    assert by_org["OrgX"]["total_contribution"] == pytest.approx(0.005 + 0.035)
    assert by_org["OrgY"]["n_plans"] == 1
    assert by_org["OrgY"]["total_contribution"] == pytest.approx(0.02)
    # sorted descending by total_contribution -> OrgX (0.04) before OrgY (0.02)
    assert [row["org"] for row in rollup] == ["OrgX", "OrgY"]


# =============================================================================
# Real-data integration: the required parity self-check
# =============================================================================


def _real_backtest_result_available() -> bool:
    return (settings.PROCESSED_DIR / diagnostics.INPUT_FILENAME).exists()


@pytest.mark.integration
def test_real_backtest_result_self_check_parity():
    if not _real_backtest_result_available():
        pytest.skip("real data/processed/backtest_result.json not present")
    result = diagnostics.load_backtest_result()
    published = result["summary"]["weighted_mae"]["logit"]
    recomputed = diagnostics.self_check_weighted_mae_logit(
        result["per_plan"], published
    )
    assert recomputed == pytest.approx(published, abs=1e-12)


@pytest.mark.integration
def test_real_build_end_to_end_reconstructs_published_total(tmp_path):
    if not _real_backtest_result_available():
        pytest.skip("real data/processed/backtest_result.json not present")
    result = diagnostics.build(output_dir=tmp_path)

    assert result["metadata"]["self_check_weighted_mae_logit"]["passed"] is True

    source = diagnostics.load_backtest_result()
    published_logit_mae = source["summary"]["weighted_mae"]["logit"]
    assert result["error_decomposition"][
        "total_weighted_mae_reconstructed"
    ] == pytest.approx(published_logit_mae, abs=1e-9)

    # bounds cover exactly the same key set as per_plan in the real artifact -- no mismatch.
    reconciliation = result["coverage"]["reconciliation"]
    assert reconciliation["keys_in_per_plan_not_in_bounds"] == []
    assert reconciliation["keys_in_bounds_not_in_per_plan"] == []

    assert (tmp_path / diagnostics.OUTPUT_FILENAME).exists()
