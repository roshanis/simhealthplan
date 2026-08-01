"""Tests for backtest/metrics.py — pure backtest scoring functions.

Hand-computable tiny fixtures only; no file I/O. See
test_backtest_run_backtest.py for the real-data integration tests that
exercise these functions against the actual 2024->2025 Maricopa backtest.
"""

from __future__ import annotations

import pytest

from backtest import metrics

OUTSIDE = "outside"


# --- share_shift ---------------------------------------------------------------


def test_share_shift_basic_difference():
    share_2025 = {"A": 0.30, "B": 0.10, OUTSIDE: 0.60}
    share_2024 = {"A": 0.20, "B": 0.15, OUTSIDE: 0.65}
    result = metrics.share_shift(share_2025, share_2024)
    assert result["A"] == pytest.approx(0.10)
    assert result["B"] == pytest.approx(-0.05)
    assert result[OUTSIDE] == pytest.approx(-0.05)


def test_share_shift_missing_key_defaults_to_zero_on_either_side():
    # "C" is new in 2025 (no 2024 share); "D" existed in 2024 but the row is
    # absent from the 2025 dict entirely (e.g. terminated with no successor).
    share_2025 = {"C": 0.05}
    share_2024 = {"D": 0.07}
    result = metrics.share_shift(share_2025, share_2024)
    assert result["C"] == pytest.approx(0.05)
    assert result["D"] == pytest.approx(-0.07)


# --- per_plan_abs_error ---------------------------------------------------------


def test_per_plan_abs_error_hand_computed():
    predicted = {"A": 0.30, "B": 0.05}
    actual = {"A": 0.25, "B": 0.05}
    result = metrics.per_plan_abs_error(predicted, actual)
    assert result["A"] == pytest.approx(0.05)
    assert result["B"] == pytest.approx(0.0)


# --- weighted_mae ----------------------------------------------------------------


def test_weighted_mae_hand_computed_equal_weights():
    # |0.05|, |0.02|, |0.10| with equal weights 1,1,1 -> mean = 0.17/3
    predicted = {"A": 0.30, "B": 0.12, "C": 0.40}
    actual = {"A": 0.25, "B": 0.10, "C": 0.50}
    weights = {"A": 1.0, "B": 1.0, "C": 1.0}
    result = metrics.weighted_mae(predicted, actual, weights)
    assert result == pytest.approx((0.05 + 0.02 + 0.10) / 3.0)


def test_weighted_mae_hand_computed_unequal_weights():
    # errors: A=0.05 (w=100), B=0.02 (w=300) -> (0.05*100 + 0.02*300)/400 = 0.0275
    predicted = {"A": 0.30, "B": 0.12}
    actual = {"A": 0.25, "B": 0.10}
    weights = {"A": 100.0, "B": 300.0}
    result = metrics.weighted_mae(predicted, actual, weights)
    assert result == pytest.approx((0.05 * 100.0 + 0.02 * 300.0) / 400.0)


def test_weighted_mae_excludes_keys():
    predicted = {"A": 0.30, "OUT": 0.9}
    actual = {"A": 0.25, "OUT": 0.5}
    weights = {"A": 10.0, "OUT": 1000.0}
    result = metrics.weighted_mae(predicted, actual, weights, exclude_keys={"OUT"})
    assert result == pytest.approx(0.05)


def test_weighted_mae_zero_total_weight_returns_zero():
    result = metrics.weighted_mae({"A": 0.1}, {"A": 0.2}, {"A": 0.0})
    assert result == 0.0


# --- directional_accuracy --------------------------------------------------------


def test_directional_accuracy_hand_computed():
    # A: predicted up, actual up -> correct
    # B: predicted down, actual down -> correct
    # C: predicted up, actual down -> wrong
    # -> 2/3
    predicted_shift = {"A": 0.02, "B": -0.01, "C": 0.03}
    actual_shift = {"A": 0.01, "B": -0.02, "C": -0.02}
    result = metrics.directional_accuracy(predicted_shift, actual_shift)
    assert result == pytest.approx(2.0 / 3.0)


def test_directional_accuracy_excludes_both_zero_shift_plans():
    # "Z" has zero predicted AND zero actual shift -> excluded from the denominator
    predicted_shift = {"A": 0.02, "Z": 0.0}
    actual_shift = {"A": 0.02, "Z": 0.0}
    result = metrics.directional_accuracy(predicted_shift, actual_shift)
    assert result == pytest.approx(1.0)


def test_directional_accuracy_excludes_suppressed_both_years():
    predicted_shift = {"A": 0.02, "S": -0.05}
    actual_shift = {"A": -0.02, "S": 0.05}  # S would be "wrong" if counted
    result = metrics.directional_accuracy(predicted_shift, actual_shift, suppressed_both_years={"S"})
    assert result == pytest.approx(0.0)  # only A counted, and A is wrong


def test_directional_accuracy_zero_vs_nonzero_counts_as_mismatch():
    predicted_shift = {"A": 0.0}
    actual_shift = {"A": 0.05}
    result = metrics.directional_accuracy(predicted_shift, actual_shift)
    assert result == pytest.approx(0.0)


def test_directional_accuracy_no_evaluable_plans_returns_none():
    result = metrics.directional_accuracy({"Z": 0.0}, {"Z": 0.0})
    assert result is None


# --- select_best_naive -------------------------------------------------------------


def test_select_best_naive_picks_lower_mae():
    assert metrics.select_best_naive({"no_change": 0.05, "trend": 0.03}) == "trend"
    assert metrics.select_best_naive({"no_change": 0.02, "trend": 0.03}) == "no_change"


def test_select_best_naive_ignores_unavailable_none_entries():
    assert metrics.select_best_naive({"no_change": 0.05, "trend": None}) == "no_change"


def test_select_best_naive_raises_if_nothing_available():
    with pytest.raises(ValueError):
        metrics.select_best_naive({"no_change": None, "trend": None})


# --- beats_naive ---------------------------------------------------------------------


def test_beats_naive_true_when_both_conditions_hold():
    result = metrics.beats_naive(
        model_weighted_mae=0.02, model_directional_accuracy=0.7, naive_weighted_mae=0.05, naive_directional_accuracy=0.6
    )
    assert result is True


def test_beats_naive_false_when_mae_worse():
    result = metrics.beats_naive(
        model_weighted_mae=0.06, model_directional_accuracy=0.9, naive_weighted_mae=0.05, naive_directional_accuracy=0.6
    )
    assert result is False


def test_beats_naive_false_when_directional_worse_even_if_mae_better():
    result = metrics.beats_naive(
        model_weighted_mae=0.02, model_directional_accuracy=0.4, naive_weighted_mae=0.05, naive_directional_accuracy=0.6
    )
    assert result is False


def test_beats_naive_none_when_model_variant_not_computed():
    result = metrics.beats_naive(
        model_weighted_mae=None, model_directional_accuracy=None, naive_weighted_mae=0.05, naive_directional_accuracy=0.6
    )
    assert result is None


def test_beats_naive_false_when_directional_accuracy_unavailable():
    result = metrics.beats_naive(
        model_weighted_mae=0.01, model_directional_accuracy=None, naive_weighted_mae=0.05, naive_directional_accuracy=0.6
    )
    assert result is False


def test_beats_naive_raises_without_a_naive_baseline():
    with pytest.raises(ValueError):
        metrics.beats_naive(
            model_weighted_mae=0.01, model_directional_accuracy=0.5, naive_weighted_mae=None, naive_directional_accuracy=0.5
        )
