/**
 * Core scenario-recompute logic shared by `/api/scenario` and the
 * `/scenario` server page's initial baseline render. Pure aside from the
 * seeded (deterministic) Monte Carlo draws in `monteCarloShares` -- no I/O,
 * no LLM calls; every number here comes from the existing TS choice-model
 * engine (`lib/choice-model/`) run against `scenario_inputs.json`.
 *
 * "Aggregate weighted share" = the same weight-blended aggregation
 * `pipeline/choice_model/predict.py::aggregate_weighted_shares` performs:
 * each archetype's softmax choice probabilities, blended by
 * `archetype.weight / sum(weights)`.
 */

import { archetypeChoiceProbabilities } from "@/lib/choice-model/engine";
import { monteCarloShares, type MonteCarloBand } from "@/lib/choice-model/monteCarlo";
import type { Archetype, ChoiceProbabilities, CoefficientsFile, Plan } from "@/lib/choice-model/types";
import { applyChanges } from "@/lib/scenario/applyChanges";
import type { ScenarioChange } from "@/lib/scenario/schema";

/** Default draw count for the API route's Monte Carlo bounds. Chosen to
 * comfortably clear the <1s round-trip budget (see `tests/api/scenario.test.ts`'s
 * timing assertion) while still giving a meaningfully shaped p10/p90 band --
 * `monteCarloShares`'s own default (200) computes baseline + scenario bounds
 * (400 draws x 80 archetypes) well under budget in practice; this constant
 * exists so the route and its test share one documented number rather than
 * two independent magic constants. */
export const DEFAULT_SCENARIO_DRAWS = 200;
export const DEFAULT_SCENARIO_SEED = 42;

/**
 * `outsideOptionKey` MUST be passed explicitly and MUST match the key
 * `archetypes`' `prior_plan_year1` maps use for the outside option --
 * `scenario_inputs.json`'s archetypes have their Year-1 priors
 * re-expressed over **2025** plan keys (see `export_artifacts.
 * build_scenario_inputs`), so their outside-option key is
 * `scenario_inputs.outside_option_key` ("other_or_no_ma_2025"), NOT
 * `coefficients.json`'s `outside_option_key` (the Year-1/2024 key,
 * "other_or_no_ma_2024") that `archetypeChoiceProbabilities` would default
 * to if this were omitted. Getting this wrong doesn't error -- it silently
 * drops the entire outside-option prior mass as "ineligible" (see
 * `choiceSets.renormalizePriorPlan`), inflating every real plan's inertia
 * term. (Caught by `tests/api/scenario.test.ts`'s real-data assertions.)
 */
export function aggregateWeightedShares(
  archetypes: Archetype[],
  plans: Plan[],
  coefficients: CoefficientsFile,
  outsideOptionKey: string,
): Record<string, number> {
  const totalWeight = archetypes.reduce((sum, a) => sum + (a.weight ?? 1.0), 0) || 1.0;
  const shares: Record<string, number> = {};

  for (const archetype of archetypes) {
    const probs: ChoiceProbabilities = archetypeChoiceProbabilities(archetype, plans, coefficients, {
      outsideKey: outsideOptionKey,
    });
    const weightShare = (archetype.weight ?? 1.0) / totalWeight;
    for (const [key, prob] of Object.entries(probs)) {
      shares[key] = (shares[key] ?? 0) + weightShare * prob;
    }
  }

  return shares;
}

export interface PlanMoveEntry {
  plan_key: string;
  org_name: string | null;
  plan_name: string | null;
  baseline_share: number;
  scenario_share: number;
  delta_pp: number;
}

export interface ScenarioResult {
  outside_option_key: string;
  changed_plan_keys: string[];
  baseline: {
    shares: Record<string, number>;
  };
  scenario: {
    shares: Record<string, number>;
    bounds: Record<string, MonteCarloBand>;
  };
  affected: PlanMoveEntry[];
  top_movers: PlanMoveEntry[];
}

export interface RunScenarioOptions {
  draws?: number;
  seed?: number;
  topMoversCount?: number;
}

function moveEntry(
  planKey: string,
  planByKey: Map<string, Plan & { org_name?: string; plan_name?: string }>,
  baselineShares: Record<string, number>,
  scenarioShares: Record<string, number>,
): PlanMoveEntry {
  const plan = planByKey.get(planKey);
  const baselineShare = baselineShares[planKey] ?? 0;
  const scenarioShare = scenarioShares[planKey] ?? 0;
  return {
    plan_key: planKey,
    org_name: plan?.org_name ?? null,
    plan_name: plan?.plan_name ?? null,
    baseline_share: baselineShare,
    scenario_share: scenarioShare,
    delta_pp: (scenarioShare - baselineShare) * 100,
  };
}

/**
 * Runs one scenario end to end: applies `changes` to `basePlans`, computes
 * baseline (unmodified) and scenario (modified) aggregate shares, seeded
 * Monte Carlo p10/p50/p90 bounds for the scenario, and the top movers by
 * |delta_pp| (excluding the plans directly changed, which are surfaced
 * separately as `affected`).
 */
export function runScenario(
  archetypes: Archetype[],
  basePlans: Plan[],
  coefficients: CoefficientsFile,
  changes: ScenarioChange[],
  outsideOptionKey: string,
  opts: RunScenarioOptions = {},
): ScenarioResult {
  const draws = opts.draws ?? DEFAULT_SCENARIO_DRAWS;
  const seed = opts.seed ?? DEFAULT_SCENARIO_SEED;
  const topMoversCount = opts.topMoversCount ?? 5;

  const { plans: scenarioPlans, changedPlanKeys } = applyChanges(basePlans, changes);

  const baselineShares = aggregateWeightedShares(archetypes, basePlans, coefficients, outsideOptionKey);
  const scenarioShares = aggregateWeightedShares(archetypes, scenarioPlans, coefficients, outsideOptionKey);
  const scenarioBounds = monteCarloShares(archetypes, scenarioPlans, coefficients, { draws, seed, outsideKey: outsideOptionKey });

  const planByKey = new Map(scenarioPlans.map((p) => [p.plan_key, p as Plan & { org_name?: string; plan_name?: string }]));

  const affected = changedPlanKeys.map((key) => moveEntry(key, planByKey, baselineShares, scenarioShares));

  const changedSet = new Set(changedPlanKeys);
  const moverCandidates = scenarioPlans
    .map((p) => p.plan_key)
    .filter((key) => !changedSet.has(key))
    .map((key) => moveEntry(key, planByKey, baselineShares, scenarioShares))
    .sort((a, b) => Math.abs(b.delta_pp) - Math.abs(a.delta_pp));

  const topMovers = moverCandidates.slice(0, topMoversCount);

  return {
    outside_option_key: outsideOptionKey,
    changed_plan_keys: changedPlanKeys,
    baseline: { shares: baselineShares },
    scenario: { shares: scenarioShares, bounds: scenarioBounds },
    affected,
    top_movers: topMovers,
  };
}
