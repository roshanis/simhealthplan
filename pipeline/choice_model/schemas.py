"""Pydantic schemas for the Phase 3 choice-model JSON artifacts.

Used to validate ``data/processed/plans_2024.json``, ``plans_2025.json``,
and ``coefficients.json`` at build time (fail loudly on a malformed
artifact) and in tests (schema-validate the committed files). ``metadata``
blocks are intentionally typed as plain ``dict`` -- they carry documentation
and provenance notes, not values other modules branch on, so a strict
sub-schema would add churn without catching real bugs.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PlanRecordBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_key: str
    contract_id: str
    plan_id: str
    org_name: str
    plan_name: str
    plan_type_raw: str
    plan_type: str
    is_ppo: bool
    snp_type: str
    premium_part_c: float
    premium_part_d: float
    premium_total: float
    deductible: float
    moop_inn: float
    imputed_moop: bool
    moop_imputation_method: str | None
    star_rating_raw: str
    star_rating: float
    imputed_star: bool
    has_comprehensive_dental: bool
    has_vision: bool
    has_hearing_aids: bool
    has_otc_or_flex: bool
    year: int


class PlanRecord2024(PlanRecordBase):
    enrollment_2024_03: float


class PlanRecord2025(PlanRecordBase):
    enrollment_2025_03: float


class PlansFile2024(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: dict
    plans: list[PlanRecord2024]


class PlansFile2025(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: dict
    plans: list[PlanRecord2025]


class CoefficientsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: dict
    base_coefficients: dict[str, float]
    segment_multipliers: dict[str, dict[str, float]]
    attribute_scaling: dict
    choice_set_rules: dict
    outside_option_key: str
