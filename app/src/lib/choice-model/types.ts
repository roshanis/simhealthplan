/**
 * Types for the Phase 3 multinomial-logit choice model, mirroring the JSON
 * artifacts written by the Python pipeline (`data/processed/plans_2024.json`
 * / `plans_2025.json`, `data/processed/archetypes.json`,
 * `data/processed/coefficients.json`) and the Pydantic schemas that validate
 * them (`pipeline/choice_model/schemas.py`).
 *
 * This module is the TypeScript counterpart of
 * `pipeline/choice_model/utility.py` + `pipeline/choice_model/choice_sets.py`
 * (see that module's docstring for the full utility spec). It is deliberately
 * plain data / structural typing -- no classes -- so a real
 * `plans_2025.json` record or `archetypes.json` record can be used directly
 * wherever a `Plan` / `Archetype` is expected.
 */

/** The nine base multinomial-logit coefficients (see coefficients.json's
 * `base_coefficients` and utility.py's `BASE_COEFFICIENT_NAMES`). */
export interface BaseCoefficients {
  b_premium: number;
  b_moop: number;
  b_dental: number;
  b_vision_hearing: number;
  b_otc: number;
  b_star: number;
  b_ppo: number;
  b_inertia: number;
  b_outside: number;
}

/** Coefficient name -> multiplier overrides for one attitude segment.
 * A missing coefficient name implicitly multiplies by 1.0 (see
 * `segmentCoefficients` in utility.ts). */
export type SegmentMultipliers = Partial<Record<keyof BaseCoefficients, number>>;

/** The full `data/processed/coefficients.json` artifact shape (matches
 * `choice_model.schemas.CoefficientsFile`). Only `base_coefficients` and
 * `outside_option_key` are consumed at runtime by this port -- segment
 * multipliers and attribute-scaling constants are hardcoded identically in
 * both languages (utility.ts / utility.py) rather than read from this file,
 * exactly as the Python side does; `segment_multipliers` /
 * `attribute_scaling` / `choice_set_rules` here are documentation-only
 * passthroughs of those same hardcoded values. */
export interface CoefficientsFile {
  metadata?: unknown;
  base_coefficients: BaseCoefficients;
  segment_multipliers?: Record<string, SegmentMultipliers>;
  attribute_scaling?: unknown;
  choice_set_rules?: unknown;
  outside_option_key: string;
}

/** One plan record, matching `choice_model.schemas.PlanRecordBase` (plus the
 * year-specific `enrollment_{year}_{month}` field, exposed generically here
 * as optional `enrollment_2024_03` / `enrollment_2025_03`). Only the fields
 * `utility.ts` / `choiceSets.ts` actually read are required; the rest are
 * optional so a full `plans_2025.json` record satisfies this type as-is. */
export interface Plan {
  plan_key: string;
  contract_id?: string;
  plan_id?: string;
  org_name?: string;
  plan_name?: string;
  plan_type_raw?: string;
  plan_type?: string;
  is_ppo: boolean;
  snp_type: string;
  premium_part_c?: number;
  premium_part_d?: number;
  premium_total: number;
  deductible?: number;
  moop_inn: number;
  imputed_moop?: boolean;
  moop_imputation_method?: string | null;
  star_rating_raw?: string;
  /** Nullable to mirror plan_attributes.py's pre-imputation shape; treated
   * as the neutral 3.5 center by `planUtility` when absent, same as
   * utility.py's `plan.get("star_rating")` fallback. */
  star_rating?: number | null;
  imputed_star?: boolean;
  has_comprehensive_dental: boolean;
  has_vision: boolean;
  has_hearing_aids: boolean;
  has_otc_or_flex: boolean;
  year?: number;
  enrollment_2024_03?: number;
  enrollment_2025_03?: number;
}

/** One archetype record, matching `data/processed/archetypes.json`'s
 * `archetypes[]` entries. Only the fields the choice model reads
 * (`age_band`, `attitude_segment`, `dual_proxy`, `prior_plan_year1`) are
 * required; the rest are optional demographic/provenance metadata. */
export interface Archetype {
  id: string;
  age_band: string;
  attitude_segment: string;
  dual_proxy: boolean;
  income_tier?: string;
  race_eth?: string;
  share_of_population?: number;
  weight?: number;
  traits?: string[];
  /** plan_key/outside_key -> Year-1 prior probability. A missing key
   * defaults to 0.0 (see `choiceProbabilities` / `renormalizePriorPlan`). */
  prior_plan_year1: Record<string, number>;
}

/** plan_key/outside_key -> softmax choice probability. Always sums to 1.0
 * (up to floating-point error) over exactly the eligible plans passed in
 * plus the outside option. */
export type ChoiceProbabilities = Record<string, number>;
