"""Pydantic schema for ``data/processed/backtest_result.json``.

Mirrors ``choice_model/schemas.py``'s conventions: ``extra="forbid"`` on
every structural model so a field-name drift between ``run_backtest.py``'s
emitted dict and this schema fails loudly at build time (``build()`` calls
``BacktestResult.model_validate`` before writing to disk) and in tests,
rather than silently shipping a malformed artifact. ``metadata`` stays a
plain ``dict`` -- it carries documentation/provenance, not values other code
branches on.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PerPlanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_key: str
    name: str
    org: str | None
    enrollment_2024: float
    share_2024: float
    share_2025_actual: float
    share_2025_pred_logit: float
    share_2025_pred_blended: float | None
    share_2025_naive_nochange: float
    share_2025_naive_trend: float | None
    shift_actual: float
    shift_pred_logit: float
    shift_pred_blended: float | None
    shift_naive_nochange: float
    shift_naive_trend: float | None
    abs_error_logit: float
    abs_error_blended: float | None
    abs_error_naive_nochange: float
    abs_error_naive_trend: float | None


class VariantFloats(BaseModel):
    """One float per scored variant. ``blended``/``trend`` are ``None``
    when that variant wasn't computed this run (no ``y2_predictions.json``
    / trend structurally unavailable, respectively)."""

    model_config = ConfigDict(extra="forbid")

    logit: float
    blended: float | None
    no_change: float
    trend: float | None


class VariantOptionalFloats(BaseModel):
    """Same shape as VariantFloats but every field is nullable -- used for
    directional_accuracy, which can legitimately be None (no evaluable
    plans -- see metrics.directional_accuracy)."""

    model_config = ConfigDict(extra="forbid")

    logit: float | None
    blended: float | None
    no_change: float | None
    trend: float | None


class BeatsNaive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logit: bool
    blended: bool | None


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weighted_mae: VariantFloats
    outside_share_error: VariantFloats
    directional_accuracy: VariantOptionalFloats
    best_naive: dict
    beats_naive: BeatsNaive


class PlanBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p10: float
    p50: float
    p90: float


class BacktestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: dict
    per_plan: list[PerPlanRecord]
    summary: Summary
    bounds: dict[str, PlanBounds]
