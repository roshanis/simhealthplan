"""Phase 5+ post-hoc diagnostics: three analyses run entirely against the
already-committed ``data/processed/backtest_result.json`` artifact -- no
raw CMS data, no ``data/interim/*.parquet``, no network access required (the
CMS host is blocked in this environment; ``make backtest`` cannot be
re-run here). Every function in this module is a **pure function of the
backtest artifact's own fields** -- read from disk once by
``load_backtest_result``/``build`` below, never re-derived from anything
this module can't see.

Mirrors ``backtest/metrics.py``'s "pure module" discipline: functions take
plain dicts/lists and return plain dicts/lists, and every weighting /
normalization decision reuses ``backtest.metrics`` directly (``weighted_mae``,
``share_shift``, ``directional_accuracy``) rather than re-deriving the
weighting arithmetic here -- see each function's docstring for exactly
which ``metrics.py`` function it calls.

Three analyses, run and reported independently (see module-level constants
below for names):

  A. **Confidence-bound coverage** (``coverage_analysis``): the Monte Carlo
     p10/p50/p90 bounds ``bounds.py`` computes are never checked against
     the actual outcome anywhere else in the pipeline. This asks: of the
     nominal 80% (p10-p90) interval, what fraction of plans' actual 2025
     share actually landed inside it? A well-calibrated interval should
     cover ~80% of plans; badly off in either direction is a real, reportable
     finding about the Monte Carlo jitter's variance assumptions -- not
     something to explain away.

  B. **Shrinkage / damping blend** (``sweep_lambda`` / ``leave_one_plan_out_cv``):
     the backtest's headline finding is that the model has the right
     *direction* but too-large *magnitude*. A convex blend of the logit
     prediction with the no_change baseline, ``share_damped(lambda) =
     lambda*logit + (1-lambda)*no_change``, tests whether damping the
     magnitude while keeping the model's directional signal can beat
     no_change on weighted MAE. Two very different numbers are reported and
     never conflated: an **oracle** lambda* (argmin over the very data being
     scored -- optimistic, NOT a validated generalization claim) and a
     **leave-one-plan-out cross-validated** estimate (a legitimate, if
     small-sample, out-of-sample generalization estimate, computable
     entirely post-hoc from this one artifact because each fold only needs
     to re-run ``metrics.weighted_mae`` with a different plan excluded --
     no re-fitting of the underlying choice model is required).

  C. **Per-plan error decomposition** (``error_contributions``): which
     individual plans account for the published weighted MAE? Each plan's
     contribution is ``(enrollment_2024 weight share) * abs_error``, summed
     to exactly the published ``weighted_mae`` figure by construction (see
     ``error_contributions`` docstring) -- ranked, with a running
     "how many plans explain 50%/80% of the total error" count, plus a
     new-entrant-vs-incumbent split derived from the one field available
     for it (``enrollment_2024``).

--- Two known, explicitly-documented limitations of working post-hoc -------

1. ``summary.directional_accuracy`` in the published artifact excludes a
   ``suppressed_both_years`` set of plan keys (CMS-suppressed in BOTH 2024
   AND 2025 -- see ``run_backtest.py``/``metrics.directional_accuracy``).
   That exact key set is NOT persisted to ``backtest_result.json`` (only
   its count, ``metadata.suppressed_both_years_plan_count`` = a handful of
   plans) -- reconstructing it requires the raw CMS CPSC suppression flags,
   which live in ``data/interim/*.parquet`` and are unavailable here. Every
   directional-accuracy figure this module computes is therefore computed
   WITHOUT that exclusion and will differ slightly (by at most that handful
   of plans) from the corresponding published number at lambda=1.0 (pure
   logit) -- this is surfaced explicitly in the output
   (``metadata.directional_accuracy_caveat``), never silently passed off as
   an exact match. (The REQUIRED self-check below is on weighted_mae only,
   which has no such gap -- see ``self_check_weighted_mae_logit``.)

2. ``bounds`` (Part A) is keyed by "plan_key" and, per the committed
   artifact, actually includes 95 entries -- 94 real plan rows plus the
   ``other_or_no_ma_2025`` outside-option row, exactly matching
   ``len(per_plan)`` (95). The outside option is not a "plan" a beneficiary
   chooses among plans, so it is excluded from the headline plan-level
   coverage figures (consistent with how ``metrics.weighted_mae``'s
   ``exclude_keys={OUTSIDE2}`` already treats it everywhere else in this
   pipeline) but its own coverage is still reported separately, not
   silently dropped. See ``reconcile_bounds_coverage``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from backtest import metrics
from choice_model.predict import OUTSIDE_KEY_YEAR2
from config.settings import settings

INPUT_FILENAME = "backtest_result.json"
OUTPUT_FILENAME = "backtest_diagnostics.json"

OUTSIDE2 = OUTSIDE_KEY_YEAR2

# 21 grid points, 0.00 .. 1.00 step 0.05 (rounded to avoid float-step drift
# like 0.15000000000000002 leaking into the output/labels).
LAMBDA_GRID: tuple[float, ...] = tuple(round(i * 0.05, 2) for i in range(21))

NOMINAL_COVERAGE = 0.80
COVERAGE_TOLERANCE = 0.05  # +/- 5pp around nominal still counts as "well-calibrated"

TOP_N_CONTRIBUTORS = 15
CUMULATIVE_TARGETS: tuple[float, ...] = (0.50, 0.80)


# =============================================================================
# Shared extraction helpers (used by all three analyses + the self-check)
# =============================================================================


def build_score_inputs(
    per_plan: list[dict], predicted_field: str
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Extracts ``(predicted, actual, weights)`` dicts keyed by ``plan_key``
    from ``backtest_result.json``'s ``per_plan`` rows -- the same triple
    ``run_backtest.py`` itself builds (``predicted_by_variant[...]``,
    ``actual_2025_shares``, ``enrollment_2024_2025keyed``) before calling
    ``metrics.weighted_mae``, just reconstructed from the already-written
    artifact instead of the live pipeline objects. ``predicted_field`` is
    one of the ``share_2025_pred_*``/``share_2025_naive_*`` field names;
    rows where that field is ``None`` (a variant not computed this run,
    e.g. blended) are skipped entirely rather than coerced to 0.0, so a
    caller can detect "variant unavailable" by an empty/partial dict."""
    predicted = {
        row["plan_key"]: row[predicted_field]
        for row in per_plan
        if row[predicted_field] is not None
    }
    actual = {row["plan_key"]: row["share_2025_actual"] for row in per_plan}
    weights = {row["plan_key"]: row["enrollment_2024"] for row in per_plan}
    return predicted, actual, weights


def plan_level_keys(per_plan: list[dict], outside_key: str = OUTSIDE2) -> list[str]:
    """Every ``plan_key`` in ``per_plan`` except the outside-option row,
    sorted for deterministic downstream iteration order."""
    return sorted(row["plan_key"] for row in per_plan if row["plan_key"] != outside_key)


def self_check_weighted_mae_logit(
    per_plan: list[dict], published_value: float, tol: float = 1e-12
) -> float:
    """Recomputes the plan-level, outside-excluded, enrollment-weighted MAE
    for the plain logit variant from ``per_plan`` alone, using
    ``metrics.weighted_mae`` directly (not reimplemented), and asserts it
    reproduces ``published_value`` (``summary.weighted_mae.logit`` in the
    real artifact) to within ``tol``. This is the module's required parity
    self-check: if this doesn't match, every other number in this module is
    suspect and should not be trusted until the mismatch is understood --
    raises ``AssertionError`` rather than logging a warning and continuing.
    """
    predicted, actual, weights = build_score_inputs(per_plan, "share_2025_pred_logit")
    recomputed = metrics.weighted_mae(
        predicted, actual, weights, exclude_keys={OUTSIDE2}
    )
    if abs(recomputed - published_value) > tol:
        raise AssertionError(
            f"self_check_weighted_mae_logit: recomputed {recomputed!r} != published {published_value!r} "
            f"(|diff|={abs(recomputed - published_value)!r} > tol={tol!r}) -- do not adjust a fudge factor, "
            "re-read metrics.weighted_mae's weighting/exclude_keys semantics instead."
        )
    return recomputed


# =============================================================================
# A. Confidence-bound coverage
# =============================================================================


def coverage_stats(
    actual: dict[str, float],
    bounds: dict[str, dict[str, float]],
    weights: dict[str, float],
    keys: Iterable[str],
) -> dict:
    """For each key in ``keys`` (evaluated only if present in BOTH
    ``actual`` and ``bounds`` -- see ``reconcile_bounds_coverage`` for how
    orchestration handles/report a mismatch rather than this function
    silently skipping it), classifies ``actual[key]`` against
    ``bounds[key]``'s ``[p10, p90]`` interval:

      * ``actual < p10``  -> "below" (the interval missed on the low side)
      * ``actual > p90``  -> "above" (the interval missed on the high side)
      * otherwise (``p10 <= actual <= p90``, BOTH ENDPOINTS INCLUSIVE)
        -> "covered"

    Returns counts, unweighted coverage (covered / evaluated), and
    enrollment-weighted coverage (``sum(weight for covered) /
    sum(weight for evaluated)``) -- ``None`` for either rate if nothing was
    evaluated. ``below_keys``/``above_keys``/``covered_keys`` are sorted
    for determinism.
    """
    below: list[str] = []
    above: list[str] = []
    covered: list[str] = []
    skipped_missing_bounds: list[str] = []

    for key in sorted(keys):
        if key not in bounds or key not in actual:
            skipped_missing_bounds.append(key)
            continue
        value = actual[key]
        p10 = bounds[key]["p10"]
        p90 = bounds[key]["p90"]
        if value < p10:
            below.append(key)
        elif value > p90:
            above.append(key)
        else:
            covered.append(key)

    n_evaluated = len(below) + len(above) + len(covered)
    unweighted_coverage = (len(covered) / n_evaluated) if n_evaluated else None

    evaluated_weight_total = sum(
        weights.get(k, 0.0) for k in (*below, *above, *covered)
    )
    covered_weight_total = sum(weights.get(k, 0.0) for k in covered)
    weighted_coverage = (
        (covered_weight_total / evaluated_weight_total)
        if evaluated_weight_total > 0
        else None
    )

    return {
        "n_evaluated": n_evaluated,
        "n_covered": len(covered),
        "n_below": len(below),
        "n_above": len(above),
        "unweighted_coverage": unweighted_coverage,
        "weighted_coverage": weighted_coverage,
        "below_keys": below,
        "above_keys": above,
        "covered_keys": covered,
        "skipped_missing_bounds_or_actual": skipped_missing_bounds,
    }


def calibration_verdict(
    coverage: float | None,
    nominal: float = NOMINAL_COVERAGE,
    tolerance: float = COVERAGE_TOLERANCE,
) -> str:
    """Canonical (machine-checkable) calibration label for an unweighted
    coverage rate against a ``nominal`` (default 80%, matching the p10/p90
    interval) target +/- ``tolerance``: one of ``"well_calibrated"``,
    ``"too_narrow_overconfident"`` (actual falls outside the interval MORE
    often than the nominal rate -- the interval is too tight),
    ``"too_wide_overconservative"`` (actual falls outside LESS often --
    the interval is wider than it needs to be), or ``"not_computable"``
    (``coverage is None``, i.e. nothing was evaluated)."""
    if coverage is None:
        return "not_computable"
    if coverage < nominal - tolerance:
        return "too_narrow_overconfident"
    if coverage > nominal + tolerance:
        return "too_wide_overconservative"
    return "well_calibrated"


def reconcile_bounds_coverage(
    per_plan: list[dict],
    bounds: dict[str, dict[str, float]],
    outside_key: str = OUTSIDE2,
) -> dict:
    """Explicit reconciliation between ``per_plan``'s key set and
    ``bounds``'s key set (per the spec: never silently drop a mismatch).
    Reports both counts, the plan-level (94, outside excluded) and total
    (95, outside included) breakdowns, and any keys present in one but
    absent from the other (empty lists in the real artifact -- bounds and
    per_plan match exactly, both at 95 total keys -- but this function does
    the actual set comparison rather than assuming that)."""
    per_plan_keys = {row["plan_key"] for row in per_plan}
    bounds_keys = set(bounds)
    return {
        "n_per_plan_rows_total": len(per_plan_keys),
        "n_per_plan_rows_plan_level": len(per_plan_keys - {outside_key}),
        "n_bounds_entries_total": len(bounds_keys),
        "n_bounds_entries_plan_level": len(bounds_keys - {outside_key}),
        "keys_in_per_plan_not_in_bounds": sorted(per_plan_keys - bounds_keys),
        "keys_in_bounds_not_in_per_plan": sorted(bounds_keys - per_plan_keys),
        "outside_key_present_in_bounds": outside_key in bounds_keys,
    }


# =============================================================================
# B. Shrinkage / damping blend
# =============================================================================


def damped_share_prediction(
    pred_logit: dict[str, float], pred_naive: dict[str, float], lam: float
) -> dict[str, float]:
    """``share_damped(lam)_k = lam * pred_logit[k] + (1 - lam) * pred_naive[k]``,
    over the union of both dicts' keys (missing -> 0.0). Both inputs are
    full share distributions that already sum to 1.0 each (every plan row
    plus the outside option, per ``run_backtest.py``'s convention), so the
    convex combination sums to 1.0 automatically -- this function still
    divides by the actual sum defensively (a no-op to within floating-point
    noise on well-formed inputs, but keeps the function correct/self-
    consistent if a caller ever passes a partial or already-filtered
    distribution). At ``lam == 0.0`` this reduces EXACTLY to ``pred_naive``
    (renormalized, a no-op since it already sums to 1.0); at ``lam == 1.0``
    it reduces EXACTLY to ``pred_logit``, likewise a no-op renormalization.
    """
    keys = set(pred_logit) | set(pred_naive)
    raw = {
        key: lam * pred_logit.get(key, 0.0) + (1.0 - lam) * pred_naive.get(key, 0.0)
        for key in keys
    }
    total = sum(raw.values())
    if total <= 0:
        return raw
    return {key: value / total for key, value in raw.items()}


def sweep_lambda(
    pred_logit: dict[str, float],
    pred_naive: dict[str, float],
    actual: dict[str, float],
    share_2024: dict[str, float],
    weights: dict[str, float],
    lambda_grid: Sequence[float],
    plan_keys: Sequence[str],
    always_exclude: Iterable[str] | None = None,
) -> list[dict]:
    """One row per ``lambda_grid`` point: weighted MAE
    (``metrics.weighted_mae``, reused unchanged) and directional accuracy
    (``metrics.share_shift`` + ``metrics.directional_accuracy``, reused
    unchanged, restricted to ``plan_keys`` via ``directional_accuracy``'s
    own ``keys`` parameter -- exactly the mechanism ``run_backtest.py``
    itself uses to scope directional accuracy to plan rows only) of the
    damped predictor at that lambda. ``always_exclude`` (typically
    ``{OUTSIDE2}``) is passed straight through to ``weighted_mae``'s
    ``exclude_keys``. This IS the in-sample sweep -- see
    ``select_oracle_lambda`` for why its argmin is an oracle, not a
    validated result, and ``leave_one_plan_out_cv`` for the honest
    out-of-sample counterpart."""
    excl = set(always_exclude) if always_exclude is not None else set()
    rows = []
    for lam in lambda_grid:
        damped = damped_share_prediction(pred_logit, pred_naive, lam)
        wmae = metrics.weighted_mae(damped, actual, weights, exclude_keys=excl)
        predicted_shift = metrics.share_shift(damped, share_2024)
        actual_shift = metrics.share_shift(actual, share_2024)
        dacc = metrics.directional_accuracy(
            predicted_shift, actual_shift, keys=plan_keys
        )
        rows.append({"lambda": lam, "weighted_mae": wmae, "directional_accuracy": dacc})
    return rows


def select_oracle_lambda(sweep_rows: list[dict]) -> dict:
    """The single sweep row with the lowest ``weighted_mae`` -- ties broken
    toward the SMALLER lambda (Python's ``min`` is stable and
    ``sweep_lambda`` emits rows in ascending-lambda order, so the first
    minimal row wins). This is an ORACLE value: it is chosen by looking at
    the weighted MAE computed on the exact same plans/year being scored, so
    it is optimistic by construction and not a claim about how a damped
    predictor would perform on a year it hadn't seen -- see
    ``leave_one_plan_out_cv`` for the honest counterpart. Raises
    ``ValueError`` on an empty sweep (should never happen with a non-empty
    ``lambda_grid``)."""
    if not sweep_rows:
        raise ValueError("select_oracle_lambda: empty sweep_rows")
    return min(sweep_rows, key=lambda row: row["weighted_mae"])


def leave_one_plan_out_cv(
    plan_keys: Sequence[str],
    pred_logit: dict[str, float],
    pred_naive: dict[str, float],
    actual: dict[str, float],
    share_2024: dict[str, float],
    weights: dict[str, float],
    lambda_grid: Sequence[float],
    always_exclude: Iterable[str] | None = None,
) -> dict:
    """Leave-one-plan-out cross-validated estimate of the damped
    predictor's generalization performance -- a legitimate out-of-sample
    estimate (unlike ``select_oracle_lambda``'s in-sample argmin), and
    computable entirely post-hoc from the committed artifact because each
    fold only needs ``metrics.weighted_mae`` re-run with one more plan
    excluded (no re-fitting of the underlying logit coefficients -- this is
    NOT re-running ``make backtest``, it only re-slices the SAME published
    predictions).

    For each ``held_out`` plan in ``plan_keys``: sweeps ``lambda_grid``,
    scoring each lambda's weighted MAE over every OTHER plan in
    ``plan_keys`` (``metrics.weighted_mae`` with ``exclude_keys =
    always_exclude | {held_out}``), and picks the lambda minimizing that
    "everyone but held_out" weighted MAE (ties -> smallest lambda, same
    stable-``min`` rule as ``select_oracle_lambda``). ``held_out`` is THEN
    scored (its own single absolute error) at that fold-chosen lambda --
    never at a lambda chosen using its own actual value, which is the
    entire point of the leave-one-out structure. The per-plan fold errors
    are aggregated into one enrollment-weighted MAE and one directional
    accuracy across all of ``plan_keys``, plus the full ``chosen_lambda``
    map for transparency (e.g. to see how stable/unstable the per-fold
    optimum is).

    All dict arguments are expected to be the FULL per-plan-derived dicts
    (i.e. may include the outside-option key) -- ``always_exclude``
    (typically ``{OUTSIDE2}``) is what keeps it out of every weighted_mae
    call here, exactly as ``sweep_lambda`` does; ``plan_keys`` itself must
    not include it.
    """
    excl_base = set(always_exclude) if always_exclude is not None else set()

    chosen_lambda: dict[str, float] = {}
    fold_predicted: dict[str, float] = {}

    for held_out in plan_keys:
        fold_excl = excl_base | {held_out}
        best_lambda: float | None = None
        best_fold_mae: float | None = None
        for lam in lambda_grid:
            damped = damped_share_prediction(pred_logit, pred_naive, lam)
            fold_mae = metrics.weighted_mae(
                damped, actual, weights, exclude_keys=fold_excl
            )
            if best_fold_mae is None or fold_mae < best_fold_mae:
                best_fold_mae, best_lambda = fold_mae, lam
        chosen_lambda[held_out] = best_lambda
        fold_predicted[held_out] = damped_share_prediction(
            pred_logit, pred_naive, best_lambda
        )[held_out]

    weighted_mae_lopo = metrics.weighted_mae(
        fold_predicted, actual, weights, exclude_keys=excl_base
    )
    predicted_shift_lopo = metrics.share_shift(fold_predicted, share_2024)
    actual_shift = metrics.share_shift(actual, share_2024)
    directional_accuracy_lopo = metrics.directional_accuracy(
        predicted_shift_lopo, actual_shift, keys=plan_keys
    )

    return {
        "weighted_mae": weighted_mae_lopo,
        "directional_accuracy": directional_accuracy_lopo,
        "chosen_lambda_by_plan": chosen_lambda,
        "n_plans": len(list(plan_keys)),
    }


def lambda_distribution(chosen_lambda_by_plan: dict[str, float]) -> dict:
    """Small summary of how the per-plan LOPO-chosen lambdas are
    distributed -- a stable ``chosen_lambda`` (most plans picking similar
    values) reads very differently from a noisy one (every plan picking a
    different corner of the grid), and this is the cheapest way to show
    that distinction without dumping the full 94-entry map into the
    headline section of the report."""
    if not chosen_lambda_by_plan:
        return {"n": 0, "mean": None, "min": None, "max": None, "counts": {}}
    values = list(chosen_lambda_by_plan.values())
    counts: dict[str, int] = {}
    for v in values:
        key = f"{v:.2f}"
        counts[key] = counts.get(key, 0) + 1
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "counts": dict(sorted(counts.items())),
    }


# =============================================================================
# C. Per-plan error decomposition
# =============================================================================


def error_contributions(
    predicted: dict[str, float],
    actual: dict[str, float],
    weights: dict[str, float],
    exclude_keys: Iterable[str] | None = None,
) -> list[dict]:
    """Per-plan contribution to ``metrics.weighted_mae``'s total:
    ``contribution_k = (weight_k / total_weight) * abs_error_k``. By
    construction ``sum(contribution_k for all k) == metrics.weighted_mae(
    predicted, actual, weights, exclude_keys)`` EXACTLY (both are the same
    sum divided by the same ``total_weight``) -- this is what "normalized
    so contributions sum to the published total" means here: no separate
    renormalization step is needed or applied, the arithmetic already sums
    to the total MAE, and the parity is asserted in this module's tests.
    Returns rows sorted descending by ``contribution`` (ties broken by
    ``plan_key`` ascending, for determinism); each row also carries
    ``weight``/``abs_error`` so contribution can be decomposed back into
    "how big" x "how wrong" per plan."""
    excluded = set(exclude_keys) if exclude_keys is not None else set()
    keys = [key for key in (set(predicted) | set(actual)) if key not in excluded]
    total_weight = sum(weights.get(key, 0.0) for key in keys)

    rows = []
    for key in keys:
        weight = weights.get(key, 0.0)
        abs_error = abs(predicted.get(key, 0.0) - actual.get(key, 0.0))
        contribution = (weight / total_weight) * abs_error if total_weight > 0 else 0.0
        rows.append(
            {
                "plan_key": key,
                "weight": weight,
                "abs_error": abs_error,
                "contribution": contribution,
            }
        )

    rows.sort(key=lambda row: (-row["contribution"], row["plan_key"]))
    return rows


def with_cumulative_share(rows: list[dict]) -> list[dict]:
    """Adds ``cumulative_contribution`` (running sum) and
    ``cumulative_share_of_total`` (running sum / total contribution) to
    each row of an already-descending-sorted ``error_contributions()``
    result. ``cumulative_share_of_total`` on the last row is exactly 1.0
    (to float precision) when ``rows`` covers the full evaluated key set."""
    total = sum(row["contribution"] for row in rows)
    out = []
    running = 0.0
    for row in rows:
        running += row["contribution"]
        out.append(
            {
                **row,
                "cumulative_contribution": running,
                "cumulative_share_of_total": (running / total) if total > 0 else 0.0,
            }
        )
    return out


def plans_to_reach_cumulative_share(
    rows_with_cumulative: list[dict], target_share: float
) -> int:
    """Smallest N such that the top-N rows (by the ``error_contributions``
    descending order already baked into ``rows_with_cumulative``) account
    for at least ``target_share`` of total contribution. Returns
    ``len(rows_with_cumulative)`` if the target is never reached (e.g.
    ``target_share > 1.0``, or a degenerate all-zero-contribution input)."""
    for index, row in enumerate(rows_with_cumulative, start=1):
        if row["cumulative_share_of_total"] >= target_share:
            return index
    return len(rows_with_cumulative)


def split_new_entrants_vs_incumbents(
    per_plan: list[dict], predicted_field: str, outside_key: str = OUTSIDE2
) -> dict:
    """Splits plan rows (outside option excluded) into "new entrants"
    (``enrollment_2024 == 0.0`` -- no 2024 predecessor/crosswalk mass at
    all, per ``run_backtest.py``'s ``_map_counts_to_2025``) vs "incumbents"
    (``enrollment_2024 > 0.0``), and reports each group's plan count and
    (informational, NOT part of the published weighted metric)
    UNweighted mean absolute error. New entrants structurally contribute
    EXACTLY 0.0 to the published weighted MAE and to ``error_contributions``
    regardless of how wrong the model is about them, because their
    ``weight`` (2024 enrollment) is 0.0 by definition -- the size-weighted
    metric is blind to new-entrant errors by construction; that's reported
    explicitly here rather than left implicit."""
    new_entrants = [
        row
        for row in per_plan
        if row["plan_key"] != outside_key and row["enrollment_2024"] == 0.0
    ]
    incumbents = [
        row
        for row in per_plan
        if row["plan_key"] != outside_key and row["enrollment_2024"] > 0.0
    ]

    def _group_stats(rows: list[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {
                "n_plans": 0,
                "unweighted_mean_abs_error": None,
                "total_enrollment_2024": 0.0,
            }
        errors = [abs(row[predicted_field] - row["share_2025_actual"]) for row in rows]
        return {
            "n_plans": n,
            "unweighted_mean_abs_error": sum(errors) / n,
            "total_enrollment_2024": sum(row["enrollment_2024"] for row in rows),
        }

    return {
        "new_entrants": _group_stats(new_entrants),
        "incumbents": _group_stats(incumbents),
        "note": (
            "new_entrants (enrollment_2024 == 0.0) contribute EXACTLY 0.0 to the published "
            "weighted MAE by construction (their weight is 0), regardless of unweighted_mean_abs_error "
            "shown here for context only -- this is a structural blind spot of the size-weighted metric, "
            "not a claim that the model is accurate for new entrants."
        ),
    }


def org_rollup(
    rows_with_contribution: list[dict], per_plan_by_key: dict[str, dict]
) -> list[dict]:
    """Aggregates ``error_contributions`` rows by ``org`` (from
    ``per_plan``'s own ``org`` field -- no external org data), summing each
    org's plan count, total weight, and total contribution share. Sorted
    descending by total contribution. A supplementary, non-headline cut
    (the task's required cut is new-entrant vs incumbent; this is an
    additional one derivable from a field already present in the data)."""
    by_org: dict[str, dict] = {}
    for row in rows_with_contribution:
        plan = per_plan_by_key.get(row["plan_key"], {})
        org = plan.get("org") or "(outside option / no org)"
        bucket = by_org.setdefault(
            org,
            {"org": org, "n_plans": 0, "total_weight": 0.0, "total_contribution": 0.0},
        )
        bucket["n_plans"] += 1
        bucket["total_weight"] += row["weight"]
        bucket["total_contribution"] += row["contribution"]

    rows = list(by_org.values())
    rows.sort(key=lambda row: (-row["total_contribution"], row["org"]))
    return rows


# =============================================================================
# Orchestration
# =============================================================================


def load_backtest_result(path: Path | None = None) -> dict:
    """Reads the committed ``backtest_result.json`` artifact. Raises
    ``FileNotFoundError`` with a clear message (rather than a bare
    ``json.JSONDecodeError`` from an empty/missing file) if it's absent --
    this is the ONE piece of input this whole module needs, and it's
    already committed to the repo, so a missing file here means something
    is genuinely wrong with the checkout, not a "re-run the pipeline"
    situation (see module docstring: the CMS host that would regenerate it
    is blocked in this environment)."""
    result_path = (
        path if path is not None else (settings.PROCESSED_DIR / INPUT_FILENAME)
    )
    if not result_path.exists():
        raise FileNotFoundError(
            f"load_backtest_result: {result_path} not found -- this module reads the already-committed "
            f"{INPUT_FILENAME}; it cannot regenerate it (make backtest requires CMS data this environment "
            "cannot download)."
        )
    return json.loads(result_path.read_text())


def build(output_dir: Path | None = None, input_path: Path | None = None) -> dict:
    """Runs all three diagnostics against the real committed
    ``backtest_result.json`` and writes ``backtest_diagnostics.json``.
    Returns the same dict that gets written. Raises ``AssertionError`` (via
    ``self_check_weighted_mae_logit``) rather than writing anything if the
    required parity self-check fails."""
    source = load_backtest_result(input_path)
    per_plan = source["per_plan"]
    bounds = source["bounds"]
    summary = source["summary"]
    metadata = source["metadata"]

    published_logit_mae = summary["weighted_mae"]["logit"]
    self_check_value = self_check_weighted_mae_logit(per_plan, published_logit_mae)

    plan_keys = plan_level_keys(per_plan)
    per_plan_by_key = {row["plan_key"]: row for row in per_plan}

    pred_logit, actual, weights = build_score_inputs(per_plan, "share_2025_pred_logit")
    pred_naive, _, _ = build_score_inputs(per_plan, "share_2025_naive_nochange")
    share_2024 = {row["plan_key"]: row["share_2024"] for row in per_plan}

    # --- A. coverage --------------------------------------------------------------
    reconciliation = reconcile_bounds_coverage(per_plan, bounds)
    plan_level_coverage = coverage_stats(actual, bounds, weights, keys=plan_keys)
    outside_coverage = coverage_stats(actual, bounds, weights, keys=[OUTSIDE2])
    verdict_unweighted = calibration_verdict(plan_level_coverage["unweighted_coverage"])
    verdict_weighted = calibration_verdict(plan_level_coverage["weighted_coverage"])

    coverage_report = {
        "nominal_interval": "p10-p90 (nominal 80% Monte Carlo interval)",
        "nominal_coverage": NOMINAL_COVERAGE,
        "calibration_tolerance": COVERAGE_TOLERANCE,
        "reconciliation": reconciliation,
        "plan_level": plan_level_coverage,
        "outside_option": outside_coverage,
        "verdict_unweighted": verdict_unweighted,
        "verdict_weighted": verdict_weighted,
        "asymmetry_note": (
            f"{plan_level_coverage['n_below']} plans fell BELOW p10 vs {plan_level_coverage['n_above']} "
            "ABOVE p90 -- a large imbalance here (as opposed to roughly equal counts on both sides) "
            "indicates directional BIAS in the point estimate (actuals systematically outside on one "
            "side), not just underestimated VARIANCE (which would miss roughly symmetrically on both "
            "sides)."
        ),
    }

    # --- B. damping -----------------------------------------------------------------
    sweep_rows = sweep_lambda(
        pred_logit,
        pred_naive,
        actual,
        share_2024,
        weights,
        LAMBDA_GRID,
        plan_keys,
        always_exclude={OUTSIDE2},
    )
    oracle = select_oracle_lambda(sweep_rows)
    lopo = leave_one_plan_out_cv(
        plan_keys,
        pred_logit,
        pred_naive,
        actual,
        share_2024,
        weights,
        LAMBDA_GRID,
        always_exclude={OUTSIDE2},
    )

    no_change_row = next(row for row in sweep_rows if row["lambda"] == 0.0)
    logit_row = next(row for row in sweep_rows if row["lambda"] == 1.0)

    oracle_beats_no_change_mae = oracle["weighted_mae"] < no_change_row["weighted_mae"]
    lopo_beats_no_change_mae = lopo["weighted_mae"] < no_change_row["weighted_mae"]

    damping_report = {
        "predictor": "share_damped(lambda) = lambda * share_2025_pred_logit + (1 - lambda) * share_2025_naive_nochange",
        "lambda_grid": list(LAMBDA_GRID),
        "sweep": sweep_rows,
        "endpoints": {
            "lambda_0_is_no_change_baseline": no_change_row,
            "lambda_1_is_pure_logit": logit_row,
        },
        "oracle": {
            **oracle,
            "caveat": (
                "ORACLE value: lambda chosen by argmin weighted_mae over the exact same plans/year being "
                "scored (in-sample). This is NOT a validated out-of-sample improvement -- it is an upper "
                "bound on what damping could achieve if you already knew the answer. See "
                "leave_one_plan_out_cv for the honest generalization estimate."
            ),
        },
        "leave_one_plan_out_cv": {
            **lopo,
            "chosen_lambda_distribution": lambda_distribution(
                lopo["chosen_lambda_by_plan"]
            ),
            "description": (
                "Honest out-of-sample estimate: for each plan, the damping lambda is chosen using every "
                "OTHER plan's weighted MAE only, then that plan alone is scored at its fold-chosen lambda. "
                "This is a legitimate generalization estimate, distinct from the oracle value above."
            ),
        },
        "verdict": {
            "oracle_beats_no_change_on_mae": oracle_beats_no_change_mae,
            "lopo_cv_beats_no_change_on_mae": lopo_beats_no_change_mae,
            "oracle_lambda": oracle["lambda"],
            "summary": (
                f"Oracle lambda*={oracle['lambda']:.2f} gives weighted MAE {oracle['weighted_mae']:.6f} "
                f"vs no_change's {no_change_row['weighted_mae']:.6f} "
                f"({'beats' if oracle_beats_no_change_mae else 'does not beat'} no_change) -- but is "
                f"in-sample/oracle. The LOPO-CV estimate is weighted MAE {lopo['weighted_mae']:.6f} "
                f"({'beats' if lopo_beats_no_change_mae else 'does not beat'} no_change out-of-sample). "
                f"If the oracle lambda* rounds to 0.00 (or the LOPO-CV chosen lambdas cluster at 0.00), "
                "that is the DEGENERATE case: the only way this predictor beats no_change on magnitude "
                "is by collapsing to no_change itself, which is not a real improvement -- state that "
                "plainly rather than reporting the MAE number alone. Directional accuracy at lambda=1.0 "
                "(pure logit, this module's own recomputation, WITHOUT the suppressed_both_years "
                "exclusion -- see module docstring) vs lambda=0.0 (no_change) shows the cost/benefit "
                "tradeoff of any lambda choice between them: see the 'sweep' array's "
                "directional_accuracy column."
            ),
        },
    }

    # --- C. error decomposition ------------------------------------------------------
    contributions = error_contributions(
        pred_logit, actual, weights, exclude_keys={OUTSIDE2}
    )
    contributions_with_cumulative = with_cumulative_share(contributions)
    total_contribution = sum(row["contribution"] for row in contributions)

    top_rows = []
    for row in contributions_with_cumulative[:TOP_N_CONTRIBUTORS]:
        plan = per_plan_by_key[row["plan_key"]]
        top_rows.append(
            {
                "plan_key": row["plan_key"],
                "org": plan["org"],
                "name": plan["name"],
                "enrollment_2024": plan["enrollment_2024"],
                "share_2024": plan["share_2024"],
                "share_2025_actual": plan["share_2025_actual"],
                "share_2025_pred_logit": plan["share_2025_pred_logit"],
                "abs_error": row["abs_error"],
                "contribution": row["contribution"],
                "cumulative_share_of_total": row["cumulative_share_of_total"],
            }
        )

    n_plans_for_targets = {
        f"{int(target * 100)}pct": plans_to_reach_cumulative_share(
            contributions_with_cumulative, target
        )
        for target in CUMULATIVE_TARGETS
    }

    entrant_split = split_new_entrants_vs_incumbents(per_plan, "share_2025_pred_logit")
    org_breakdown = org_rollup(contributions, per_plan_by_key)

    decomposition_report = {
        "total_weighted_mae_reconstructed": total_contribution,
        "n_plans_scored": len(contributions),
        "top_contributors": top_rows,
        "n_plans_to_reach_cumulative_share": n_plans_for_targets,
        "new_entrant_vs_incumbent_split": entrant_split,
        "org_rollup": org_breakdown,
    }

    diagnostics_result = {
        "metadata": {
            "source_artifact": INPUT_FILENAME,
            "source_metadata": {
                "seed": metadata.get("seed"),
                "year1": metadata.get("year1"),
                "year2": metadata.get("year2"),
                "eligibles_2024": metadata.get("eligibles_2024"),
                "primary_bounds_variant": metadata.get("primary_bounds_variant"),
                "n_bounds_draws": metadata.get("n_bounds_draws"),
                "suppressed_both_years_plan_count": metadata.get(
                    "suppressed_both_years_plan_count"
                ),
            },
            "self_check_weighted_mae_logit": {
                "published": published_logit_mae,
                "recomputed": self_check_value,
                "passed": True,
                "tolerance": 1e-12,
            },
            "directional_accuracy_caveat": (
                "This module's directional_accuracy figures (sweep/LOPO-CV) do NOT apply the "
                "suppressed_both_years exclusion the published summary.directional_accuracy uses (that "
                "exact plan-key set is not persisted in backtest_result.json, only its count -- see "
                "module docstring). At lambda=1.0 (pure logit) this module's directional_accuracy will "
                "therefore differ slightly from the published summary.directional_accuracy.logit."
            ),
            "n_plans_scored": len(plan_keys),
            "n_lambda_grid_points": len(LAMBDA_GRID),
        },
        "coverage": coverage_report,
        "damping": damping_report,
        "error_decomposition": decomposition_report,
    }

    dest_dir = output_dir if output_dir is not None else settings.PROCESSED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / OUTPUT_FILENAME).write_text(
        json.dumps(diagnostics_result, indent=2, sort_keys=True) + "\n"
    )

    return diagnostics_result


if __name__ == "__main__":
    out = build()
    cov = out["coverage"]
    damp = out["damping"]
    decomp = out["error_decomposition"]

    print(
        f"{OUTPUT_FILENAME}: self-check passed (recomputed weighted_mae.logit == published, tol=1e-12)"
    )

    print("\n--- A. Confidence-bound coverage (nominal 80%, p10-p90) ---")
    print(
        f"  plan-level unweighted coverage: {cov['plan_level']['unweighted_coverage']:.1%} "
        f"({cov['plan_level']['n_covered']}/{cov['plan_level']['n_evaluated']})"
    )
    print(
        f"  plan-level weighted coverage:   {cov['plan_level']['weighted_coverage']:.1%}"
    )
    print(
        f"  below p10: {cov['plan_level']['n_below']}   above p90: {cov['plan_level']['n_above']}"
    )
    print(f"  verdict (unweighted): {cov['verdict_unweighted']}")
    print(f"  verdict (weighted):   {cov['verdict_weighted']}")

    print("\n--- B. Shrinkage / damping blend ---")
    print(
        f"  no_change (lambda=0.00): weighted_mae={damp['endpoints']['lambda_0_is_no_change_baseline']['weighted_mae']:.6f}"
    )
    print(
        f"  pure logit (lambda=1.00): weighted_mae={damp['endpoints']['lambda_1_is_pure_logit']['weighted_mae']:.6f}"
    )
    print(
        f"  oracle lambda*={damp['oracle']['lambda']:.2f}  weighted_mae={damp['oracle']['weighted_mae']:.6f} "
        f"(beats no_change: {damp['verdict']['oracle_beats_no_change_on_mae']})"
    )
    print(
        f"  LOPO-CV weighted_mae={damp['leave_one_plan_out_cv']['weighted_mae']:.6f} "
        f"(beats no_change: {damp['verdict']['lopo_cv_beats_no_change_on_mae']})"
    )
    print(
        f"  LOPO-CV chosen-lambda distribution: {damp['leave_one_plan_out_cv']['chosen_lambda_distribution']['counts']}"
    )

    print("\n--- C. Per-plan error decomposition ---")
    print(
        f"  reconstructed total (should equal published weighted_mae.logit): {decomp['total_weighted_mae_reconstructed']:.6f}"
    )
    print(
        f"  plans to reach 50% of total error: {decomp['n_plans_to_reach_cumulative_share']['50pct']}"
    )
    print(
        f"  plans to reach 80% of total error: {decomp['n_plans_to_reach_cumulative_share']['80pct']}"
    )
    print("  top 5 contributors:")
    for row in decomp["top_contributors"][:5]:
        print(
            f"    {row['plan_key']:<12} {row['org'] or '':<25} contribution={row['contribution']:.6f} "
            f"cum_share={row['cumulative_share_of_total']:.1%}"
        )
