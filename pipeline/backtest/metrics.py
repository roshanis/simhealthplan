"""Phase 5 backtest scoring: pure functions, no I/O.

Mirrors ``choice_model/utility.py``'s "pure module" discipline -- every
function here takes plain dicts (plan_key/outside_key -> float) and returns
plain dicts/floats, so the same functions score the logit model, the
blended model (when available), and both naive baselines identically.
``run_backtest.py`` is the only module that wires these to real data.

All four functions operate on **share space** (eligibles-denominated,
outside option included in the dict unless explicitly excluded via
``exclude_keys``) -- never raw enrollment counts.
"""

from __future__ import annotations

from typing import Iterable


def share_shift(share_year2: dict[str, float], share_year1: dict[str, float]) -> dict[str, float]:
    """Per-key share shift: ``share_year2[k] - share_year1[k]``, over the
    union of both dicts' keys (a key missing from one side defaults to 0.0
    -- e.g. a plan brand-new in year2, or a year1 plan whose row was dropped
    entirely rather than crosswalked forward)."""
    keys = set(share_year2) | set(share_year1)
    return {key: share_year2.get(key, 0.0) - share_year1.get(key, 0.0) for key in keys}


def per_plan_abs_error(predicted: dict[str, float], actual: dict[str, float]) -> dict[str, float]:
    """Per-key ``|predicted[k] - actual[k]|``, over the union of both dicts' keys."""
    keys = set(predicted) | set(actual)
    return {key: abs(predicted.get(key, 0.0) - actual.get(key, 0.0)) for key in keys}


def weighted_mae(
    predicted: dict[str, float],
    actual: dict[str, float],
    weights: dict[str, float],
    exclude_keys: Iterable[str] | None = None,
) -> float:
    """Size-weighted mean absolute error: ``sum(w_k * |pred_k - actual_k|) / sum(w_k)``.

    ``weights`` is typically 2024 plan enrollment (raw counts, not shares --
    only relative weight matters, the denominator normalizes). Keys in
    ``exclude_keys`` (e.g. the outside option, for the headline plan-level
    MAE) are dropped from both the numerator and the weight total. A key
    present in ``predicted``/``actual`` but absent from ``weights`` gets
    weight 0.0 (contributes nothing). Returns 0.0 if the total weight over
    the evaluated keys is <= 0 (degenerate input, not a real backtest case).
    """
    excluded = set(exclude_keys) if exclude_keys is not None else set()
    keys = [key for key in (set(predicted) | set(actual)) if key not in excluded]
    total_weight = sum(weights.get(key, 0.0) for key in keys)
    if total_weight <= 0:
        return 0.0
    weighted_error_sum = sum(weights.get(key, 0.0) * abs(predicted.get(key, 0.0) - actual.get(key, 0.0)) for key in keys)
    return weighted_error_sum / total_weight


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def directional_accuracy(
    predicted_shift: dict[str, float],
    actual_shift: dict[str, float],
    suppressed_both_years: Iterable[str] | None = None,
    keys: Iterable[str] | None = None,
) -> float | None:
    """Share of plans whose predicted shift sign matches the actual shift sign.

    ``keys`` (default: the union of both shift dicts) is the candidate plan
    set to evaluate. Two exclusion rules are applied before scoring, per the
    Phase 5 spec:

      * plans in ``suppressed_both_years`` (CMS-suppressed enrollment in
        BOTH 2024 and 2025 -- no reliable actual signal either year), and
      * plans where BOTH the predicted and actual shift are exactly 0.0
        (nothing to get a "direction" right or wrong about).

    A plan where exactly one side is 0.0 and the other is nonzero counts as
    a mismatch (0 is neither "up" nor "down"). Returns ``None`` (not 0.0 --
    a real, distinguishable "not computable" signal) if every candidate plan
    was excluded.
    """
    excluded = set(suppressed_both_years) if suppressed_both_years is not None else set()
    candidate_keys = keys if keys is not None else (set(predicted_shift) | set(actual_shift))

    evaluated: list[tuple[float, float]] = []
    for key in candidate_keys:
        if key in excluded:
            continue
        predicted = predicted_shift.get(key, 0.0)
        actual = actual_shift.get(key, 0.0)
        if predicted == 0.0 and actual == 0.0:
            continue
        evaluated.append((predicted, actual))

    if not evaluated:
        return None

    correct = sum(1 for predicted, actual in evaluated if _sign(predicted) == _sign(actual))
    return correct / len(evaluated)


# --- beats-naive verdict (explicit rule, never hand-set) -------------------------------


def select_best_naive(naive_weighted_mae: dict[str, float | None]) -> str:
    """Picks the single "best naive" baseline name for the ``beats_naive``
    rule below: the lowest ``weighted_mae`` among the naive baselines that
    were actually computed this run (a ``None`` value means that baseline
    wasn't computed -- e.g. trend structurally unavailable, no 2023 CPSC
    snapshot). Raises ``ValueError`` if every naive baseline is ``None``
    (should never happen in practice: no_change is always computable)."""
    available = {name: value for name, value in naive_weighted_mae.items() if value is not None}
    if not available:
        raise ValueError("select_best_naive: no naive baseline was computed")
    return min(available, key=lambda name: available[name])


def beats_naive(
    model_weighted_mae: float | None,
    model_directional_accuracy: float | None,
    naive_weighted_mae: float | None,
    naive_directional_accuracy: float | None,
) -> bool | None:
    """The explicit ``beats_naive`` rule (never hand-set):
    ``model_weighted_mae < naive_weighted_mae AND model_directional_accuracy
    >= naive_directional_accuracy``, both measured against the single "best
    naive" baseline (see ``select_best_naive``).

    Returns ``None`` (not ``False``) if the model variant itself wasn't
    computed this run (``model_weighted_mae is None`` -- e.g. no
    ``y2_predictions.json`` yet for the blended variant): "not applicable"
    is a distinguishable outcome from "computed and lost". Returns
    ``False`` if a directional_accuracy is unavailable (``None``) on either
    side, since "beats" can't be affirmatively confirmed without it.
    """
    if model_weighted_mae is None:
        return None
    if naive_weighted_mae is None:
        raise ValueError("beats_naive: naive_weighted_mae is required (pass select_best_naive's result)")

    mae_better = model_weighted_mae < naive_weighted_mae
    if model_directional_accuracy is None or naive_directional_accuracy is None:
        return False
    directional_at_least_as_good = model_directional_accuracy >= naive_directional_accuracy
    return bool(mae_better and directional_at_least_as_good)
