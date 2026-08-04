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

// --- physicians.json ------------------------------------------------------------------

export interface PhysicianSpecialtyCount {
  specialty: string;
  clinicians: number;
}

export interface PhysicianOrgCount {
  org_name: string;
  clinicians: number;
}

export interface PhysicianTotals {
  clinicians: number;
  organizations: number;
  practice_locations: number;
  specialties: number;
  telehealth_share: number;
}

export interface PhysiciansFile {
  available: boolean;
  metadata?: Record<string, unknown>;
  totals: PhysicianTotals | null;
  top_specialties: PhysicianSpecialtyCount[];
  top_organizations: PhysicianOrgCount[];
}

// --- network_inputs.json / network_standards.json -------------------------------------

export interface NetworkOrgSpecialty {
  clinicians: number;
  zcta_idx: number[];
}

export interface NetworkOrganization {
  org_pac_id: string;
  org_name: string;
  clinicians: number;
  specialties: Record<string, NetworkOrgSpecialty>;
}

export interface NetworkInputsFile {
  available: boolean;
  metadata?: Record<string, unknown>;
  zctas: string[];
  organizations: NetworkOrganization[];
}

export interface NetworkStandardSpecialty {
  key: string;
  label: string;
  dac_specialties: string[];
  target_ratio_per_1000: number | null;
  target_source: string | null;
}

export interface NetworkStandardsFile {
  sources: string[];
  specialties: NetworkStandardSpecialty[];
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

// --- diagnostics.json ----------------------------------------------------------------
//
// Written by `pipeline/export/export_diagnostics.py` (`make export-diagnostics`), a
// trimmed pass over `data/processed/backtest_diagnostics.json` (itself written by
// `pipeline/backtest/diagnostics.py`, `make diagnostics`). Three post-hoc analyses over
// the already-committed backtest result -- see that module's docstring for the full
// methodology. These types mirror the exported JSON's shape field-for-field so the
// report panel (`components/report/DiagnosticsPanel.tsx`) can read every displayed
// number straight off the artifact, never hand-recompute or hardcode one.

export interface DiagnosticsCoveragePlanLevel {
  n_above: number;
  n_below: number;
  n_covered: number;
  n_evaluated: number;
  unweighted_coverage: number;
  weighted_coverage: number;
}

export interface DiagnosticsCoverageReconciliation {
  n_bounds_entries_plan_level: number;
  n_bounds_entries_total: number;
  n_per_plan_rows_plan_level: number;
  n_per_plan_rows_total: number;
  outside_key_present_in_bounds: boolean;
}

/** Analysis A: does the nominal p10-p90 Monte Carlo interval actually cover ~80% of
 * plans' realized 2025 share? `asymmetry_note` explains why a lopsided n_above/n_below
 * split (rather than a merely-too-narrow-but-symmetric split) points to point-estimate
 * BIAS, not just underestimated variance -- the panel must surface that distinction,
 * not just the raw coverage percentage. */
export interface DiagnosticsCoverage {
  asymmetry_note: string;
  calibration_tolerance: number;
  nominal_coverage: number;
  nominal_interval: string;
  plan_level: DiagnosticsCoveragePlanLevel;
  reconciliation: DiagnosticsCoverageReconciliation;
  verdict_unweighted: string;
  verdict_weighted: string;
}

export interface DiagnosticsDampingPoint {
  directional_accuracy: number;
  lambda: number;
  weighted_mae: number;
}

export interface DiagnosticsDampingEndpoints {
  lambda_0_is_no_change_baseline: DiagnosticsDampingPoint;
  lambda_1_is_pure_logit: DiagnosticsDampingPoint;
}

export interface DiagnosticsLopoCvDistribution {
  /** Keyed by `lambda.toFixed(2)`, e.g. `"0.00"` -> fold count. */
  counts: Record<string, number>;
  max: number;
  mean: number;
  min: number;
  n: number;
}

/** The HONEST out-of-sample estimate: each plan's fold chooses lambda using every
 * OTHER plan only, then is scored alone at that fold-chosen lambda. Never present this
 * next to the oracle figure without labelling which is which -- see `oracle` below. */
export interface DiagnosticsLopoCv {
  chosen_lambda_by_plan: Record<string, number>;
  chosen_lambda_distribution: DiagnosticsLopoCvDistribution;
  description: string;
  directional_accuracy: number;
  n_plans: number;
  weighted_mae: number;
}

/** The IN-SAMPLE/oracle lambda*: argmin weighted MAE over the exact plans/year being
 * scored. An upper bound on what damping could achieve with hindsight, not a validated
 * result -- `caveat` says so explicitly and the panel must repeat that framing rather
 * than reporting this number as if it generalizes. */
export interface DiagnosticsOracle {
  caveat: string;
  directional_accuracy: number;
  lambda: number;
  weighted_mae: number;
}

export interface DiagnosticsDampingVerdict {
  lopo_cv_beats_no_change_on_mae: boolean;
  oracle_beats_no_change_on_mae: boolean;
  oracle_lambda: number;
  summary: string;
}

/** Analysis B: `share_damped(lambda) = lambda*logit + (1-lambda)*no_change`, swept
 * across `lambda_grid`. The degenerate finding this panel must state plainly: the
 * oracle lambda* rounds to 0.00, i.e. the "best" damped predictor simply IS the
 * no-change baseline -- there is no genuine magnitude improvement available here. */
export interface DiagnosticsDamping {
  endpoints: DiagnosticsDampingEndpoints;
  lambda_grid: number[];
  leave_one_plan_out_cv: DiagnosticsLopoCv;
  oracle: DiagnosticsOracle;
  predictor: string;
  sweep: DiagnosticsDampingPoint[];
  verdict: DiagnosticsDampingVerdict;
}

export interface DiagnosticsErrorSplitGroup {
  n_plans: number;
  total_enrollment_2024: number;
  unweighted_mean_abs_error: number;
}

/** `new_entrants` (enrollment_2024 === 0) always contribute exactly 0 to the published
 * size-weighted MAE by construction (zero weight) -- a structural blind spot of the
 * weighted metric, not evidence the model is accurate for new entrants. `note` states
 * this explicitly; the panel must surface it rather than let a reader infer accuracy
 * from the absence of weighted error. */
export interface DiagnosticsNewEntrantSplit {
  incumbents: DiagnosticsErrorSplitGroup;
  new_entrants: DiagnosticsErrorSplitGroup;
  note: string;
}

export interface DiagnosticsOrgRollupRow {
  n_plans: number;
  org: string;
  total_contribution: number;
  total_weight: number;
}

export interface DiagnosticsTopContributorRow {
  abs_error: number;
  contribution: number;
  cumulative_share_of_total: number;
  enrollment_2024: number;
  name: string;
  org: string;
  plan_key: string;
  share_2024: number;
  share_2025_actual: number;
  share_2025_pred_logit: number;
}

/** Analysis C: how concentrated is the published size-weighted MAE across plans?
 * `top_contributors` is pre-sorted by `contribution` descending with a running
 * `cumulative_share_of_total`, so `top_contributors[0]` is always the single largest
 * contributor and `n_plans_to_reach_cumulative_share` gives the panel's "N plans = X%
 * of all error" headline without it having to walk the array itself. */
export interface DiagnosticsErrorDecomposition {
  n_plans_scored: number;
  n_plans_to_reach_cumulative_share: {
    "50pct": number;
    "80pct": number;
  };
  new_entrant_vs_incumbent_split: DiagnosticsNewEntrantSplit;
  org_rollup: DiagnosticsOrgRollupRow[];
  top_contributors: DiagnosticsTopContributorRow[];
  total_weighted_mae_reconstructed: number;
}

export interface DiagnosticsSelfCheck {
  passed: boolean;
  published: number;
  recomputed: number;
  tolerance: number;
}

export interface DiagnosticsMetadata {
  directional_accuracy_caveat: string;
  n_lambda_grid_points: number;
  n_plans_scored: number;
  self_check_weighted_mae_logit: DiagnosticsSelfCheck;
  source_artifact: string;
  source_metadata: Record<string, unknown>;
}

export interface DiagnosticsFile {
  coverage: DiagnosticsCoverage;
  damping: DiagnosticsDamping;
  error_decomposition: DiagnosticsErrorDecomposition;
  metadata: DiagnosticsMetadata;
}
