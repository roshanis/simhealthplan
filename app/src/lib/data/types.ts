/**
 * Types for the Phase 7 UI-facing JSON artifacts in `app/src/data/`
 * (written by `pipeline/export/export_artifacts.py`'s `build_*` functions --
 * see that module's docstring for the exact provenance of each file).
 *
 * These are deliberately separate from `lib/choice-model/types.ts`'s
 * `Plan`/`Archetype`/`CoefficientsFile` (the parity-tested engine-input
 * shapes): the files here are trimmed, UI-shaped, display artifacts.
 * `scenario_inputs.json` is the one exception -- its `plans`/`archetypes`
 * records are engine-compatible by construction (a structural superset of
 * `Plan`/`Archetype`), so the scenario engine imports those types directly
 * instead of duplicating them here (see `lib/scenario/runScenario.ts`).
 */

// --- market.json --------------------------------------------------------------------

export interface MarketPlan {
  plan_key: string;
  org_name: string;
  plan_name: string;
  plan_type: string;
  is_ppo: boolean;
  snp_type: string;
  premium_total: number;
  moop_inn: number;
  star_rating: number;
  has_comprehensive_dental: boolean;
  has_vision: boolean;
  has_hearing_aids: boolean;
  has_otc_or_flex: boolean;
  imputed_moop: boolean;
  imputed_star: boolean;
  enrollment: number;
}

export interface OrgRollup {
  org_name: string;
  plan_count: number;
  total_enrollment: number;
  avg_premium: number;
  avg_star_rating: number;
}

export interface MarketTotals {
  plan_count: number;
  total_ma_enrollment: number;
  eligibles: number;
  ma_penetration: number | null;
}

export interface MarketData {
  metadata: {
    year1: number;
    year2: number;
    enrollment_month: number;
  };
  plans: Record<string, MarketPlan[]>;
  org_rollups: Record<string, OrgRollup[]>;
  market_totals: Record<string, MarketTotals>;
}

// --- backtest.json -------------------------------------------------------------------

export type ModelVariant = "logit" | "blended";
export type NaiveVariant = "no_change" | "trend";

export interface BacktestSummary {
  best_naive: {
    selected: NaiveVariant;
    weighted_mae: Record<NaiveVariant, number>;
  };
  beats_naive: Record<ModelVariant, boolean | null>;
  directional_accuracy: Record<ModelVariant | NaiveVariant, number | null>;
  outside_share_error: Record<ModelVariant | NaiveVariant, number | null>;
  weighted_mae: Record<ModelVariant | NaiveVariant, number | null>;
}

export interface PerPlanRow {
  plan_key: string;
  name: string;
  org: string | null;
  enrollment_2024: number;
  share_2024: number;
  share_2025_actual: number;
  share_2025_pred_logit: number;
  share_2025_pred_blended: number | null;
  share_2025_naive_nochange: number;
  share_2025_naive_trend: number;
  abs_error_logit: number;
  abs_error_blended: number | null;
  abs_error_naive_nochange: number;
  abs_error_naive_trend: number;
}

export interface MonteCarloBoundRecord {
  p10: number;
  p50: number;
  p90: number;
}

export interface BacktestData {
  metadata: Record<string, unknown>;
  summary: BacktestSummary;
  per_plan: PerPlanRow[];
  bounds: Record<string, MonteCarloBoundRecord>;
}

// --- archetypes.json (display) --------------------------------------------------------

export interface ArchetypePriorPlan {
  plan_key: string;
  prior_prob: number;
}

export interface ArchetypeDisplayRecord {
  id: string;
  demographics: {
    age_band: string;
    income_tier: string | null;
    race_eth: string | null;
  };
  segment: string;
  dual_proxy: boolean;
  weight: number;
  share_of_population: number | null;
  traits: string[];
  prior_outside_share: number;
  top_prior_plans: ArchetypePriorPlan[];
}

export interface ArchetypesDisplayFile {
  metadata: {
    archetype_count: number;
    population_total: number | null;
    top_prior_plans_n: number;
    outside_option_key: string;
  };
  archetypes: ArchetypeDisplayRecord[];
}

// --- personas.json -----------------------------------------------------------------

/** One `data/processed/personas.json` record, matching
 * `pipeline/llm/run_persona_pass.py`'s `personas.append({...})` shape
 * exactly (`id` is the archetype id it belongs to, NOT a persona-specific
 * id). Optional here (rather than on the pipeline side) purely so this
 * app-side type degrades gracefully if a future prompt-schema field is
 * added/renamed before this type is updated to match. */
export interface PersonaRecord {
  id: string;
  name?: string;
  backstory?: string;
  ranked_plan_keys?: string[];
  switching_propensity?: number;
  rationale?: string;
  consideration_set?: string[];
  [key: string]: unknown;
}

export interface PersonasFile {
  available: boolean;
  metadata?: Record<string, unknown>;
  personas: PersonaRecord[];
}

// --- scenario_inputs.json -------------------------------------------------------------

export interface ScenarioPlanRecord {
  plan_key: string;
  org_name: string;
  plan_name: string;
  plan_type: string;
  is_ppo: boolean;
  snp_type: string;
  premium_total: number;
  moop_inn: number;
  star_rating: number | null;
  has_comprehensive_dental: boolean;
  has_vision: boolean;
  has_hearing_aids: boolean;
  has_otc_or_flex: boolean;
  imputed_moop: boolean;
  imputed_star: boolean;
  enrollment: number;
}

export interface ScenarioArchetypeRecord {
  id: string;
  age_band: string;
  attitude_segment: string;
  dual_proxy: boolean;
  weight: number;
  eligible_plan_keys: string[];
  prior_plan_year1: Record<string, number>;
}

export interface ScenarioInputsFile {
  metadata: {
    year: number;
    outside_option_key: string;
  };
  outside_option_key: string;
  plans: ScenarioPlanRecord[];
  archetypes: ScenarioArchetypeRecord[];
}
