"""Phase 5 ground-truth enrollment shares from real CMS interim data.

Generic across year and plan universe (not hard-coded to 2025): used for the
2025 backtest target per the spec, AND reused as-is for the 2024 baseline
share/weight basis (``run_backtest.py``) and the 2023 trend-baseline input
(``baselines.py``) -- same suppression handling, same "outside = eligibles
minus modeled MA enrollment" formula, every year.

Reads directly from the interim CPSC (``cpsc_<year>_<month>.parquet``) and
penetration (``penetration_<year>_<month>.parquet``) tables produced by
``parse/cpsc.py`` / ``parse/penetration.py`` -- independent of
``choice_model/plan_attributes.py``'s already-imputed ``enrollment_*``
columns, so the backtest's ground truth doesn't depend on the same code path
used to build the model's own input plan tables (even though, per
``test_real_actual_shares_2025_matches_plans_2025_enrollment_field``, they
agree exactly -- both apply the identical suppressed-cell convention).

Suppression convention: CMS suppresses plan/county enrollment cells <= 10
with the sentinel ``"*"`` (see ``parse/cpsc.py``); both here and in
``archetypes/plan_priors.py`` / ``choice_model/plan_attributes.py``, that's
imputed to a fixed placeholder count (``SUPPRESSED_ENROLLMENT_IMPUTE = 5``,
the same value, documented independently in each module rather than shared
as a single cross-package constant -- there's no natural shared home for it
between ``archetypes``, ``choice_model``, and ``backtest``).
"""

from __future__ import annotations

import pandas as pd

SUPPRESSED_ENROLLMENT_IMPUTE = 5


def plan_key(contract_id: str, plan_id: str) -> str:
    return f"{contract_id}-{plan_id}"


def enrollment_by_plan(
    cpsc_df: pd.DataFrame,
    plan_keys: list[str],
    impute_suppressed: int = SUPPRESSED_ENROLLMENT_IMPUTE,
) -> dict[str, float]:
    """Actual enrollment per ``plan_keys`` (raw count, suppressed cells
    imputed to ``impute_suppressed``). Rows whose plan_key isn't in
    ``plan_keys`` are dropped (e.g. legacy/national plans outside the
    landscape universe -- see ``archetypes/plan_priors.py``'s module
    docstring for the same convention at the archetype-prior stage). A
    requested plan_key with no matching CPSC rows at all gets 0.0. Multiple
    rows for the same plan_key (e.g. more than one SSA-county row mapping to
    this county's FIPS) are summed.
    """
    df = cpsc_df.copy()
    df["plan_key"] = [plan_key(c, p) for c, p in zip(df["contract_id"], df["plan_id"])]

    sub = df[df["plan_key"].isin(plan_keys)].copy()
    enrollment = pd.to_numeric(sub["enrollment"], errors="coerce")
    suppressed = sub["suppressed"].astype(bool)
    sub["enrollment_value"] = enrollment.where(~suppressed, float(impute_suppressed)).astype(float)

    by_plan = sub.groupby("plan_key")["enrollment_value"].sum()
    return {key: float(by_plan.get(key, 0.0)) for key in plan_keys}


def eligibles_total(penetration_df: pd.DataFrame) -> float:
    """The single county-level eligibles count (one row per year_month)."""
    return float(penetration_df["eligibles"].iloc[0])


def actual_counts(
    cpsc_df: pd.DataFrame,
    penetration_df: pd.DataFrame,
    plan_keys: list[str],
    outside_key: str,
    impute_suppressed: int = SUPPRESSED_ENROLLMENT_IMPUTE,
) -> dict[str, float]:
    """Actual enrollment counts per plan_key + ``outside_key``.

    ``outside_key``'s count = eligibles - sum(modeled-plan enrollment) --
    "modeled" meaning the ``plan_keys`` universe passed in, exactly matching
    ``archetypes/plan_priors.py::cpsc_plan_targets``'s outside-residual
    definition (not re-derived, just applied to a caller-supplied plan
    universe/year instead of a hard-coded one).
    """
    counts = enrollment_by_plan(cpsc_df, plan_keys, impute_suppressed)
    eligibles = eligibles_total(penetration_df)
    landscape_total = sum(counts.values())
    counts[outside_key] = eligibles - landscape_total
    return counts


def suppressed_plan_keys(cpsc_df: pd.DataFrame, plan_keys: list[str]) -> set[str]:
    """The subset of ``plan_keys`` whose CPSC row(s) for this county are
    CMS-suppressed (small-cell privacy) -- i.e. at least one matching row
    has ``suppressed == True``. Used by ``run_backtest.py`` to build the
    "suppressed in both years" exclusion set for ``metrics.directional_accuracy``."""
    df = cpsc_df.copy()
    df["plan_key"] = [plan_key(c, p) for c, p in zip(df["contract_id"], df["plan_id"])]
    sub = df[df["plan_key"].isin(plan_keys)]
    if sub.empty:
        return set()
    suppressed_mask = sub.groupby("plan_key")["suppressed"].any()
    return set(suppressed_mask[suppressed_mask].index)


def actual_shares(
    cpsc_df: pd.DataFrame,
    penetration_df: pd.DataFrame,
    plan_keys: list[str],
    outside_key: str,
    impute_suppressed: int = SUPPRESSED_ENROLLMENT_IMPUTE,
) -> dict[str, float]:
    """``actual_counts`` divided through by eligibles -- sums to 1.0."""
    counts = actual_counts(cpsc_df, penetration_df, plan_keys, outside_key, impute_suppressed)
    eligibles = eligibles_total(penetration_df)
    return {key: value / eligibles for key, value in counts.items()}
