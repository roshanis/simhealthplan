/**
 * Multinomial-logit utility and softmax choice-probability functions.
 *
 * 1:1 TypeScript port of `pipeline/choice_model/utility.py` (the frozen
 * Python parity source of truth -- read that module's docstring for the
 * full utility spec). Mirrors its structure and function names (camelCased)
 * exactly, including the hardcoded `SEGMENT_MULTIPLIERS` / attribute-scaling
 * constants: those are NOT read from `coefficients.json` at runtime by
 * either language (that JSON's `segment_multipliers` / `attribute_scaling`
 * blocks are documentation-only dumps of these same hardcoded values).
 *
 * Utility spec (see coefficients.json for the fitted/documented values):
 *
 *     U(archetype, plan) =
 *         b_premium * (premium_total / 10)
 *       + b_moop * (moop_inn / 1000)
 *       + b_dental * has_comprehensive_dental
 *       + b_vision_hearing * (has_vision + has_hearing_aids) / 2
 *       + b_otc * has_otc_or_flex
 *       + b_star * (star_rating - 3.5)
 *       + b_ppo * is_ppo
 *       + b_inertia * prior_prob(archetype, plan)
 *
 *     U(archetype, outside) = b_outside + b_inertia * prior_prob(archetype, outside)
 *
 * Archetype-level coefficients = base coefficients * SEGMENT_MULTIPLIERS[segment]
 * (missing entries default to 1.0; the "mixed" catch-all segment and any
 * unrecognized segment name are the identity -- all multipliers 1.0).
 *
 * Probabilities are a softmax over whatever `plans` array is passed in. This
 * module has NO knowledge of D-SNP/I-SNP/C-SNP eligibility rules -- callers
 * (see choiceSets.ts, or engine.ts's `archetypeChoiceProbabilities`) must
 * pre-filter `plans` to the archetype's eligible choice set before calling
 * `choiceProbabilities`.
 */

import { softmax } from "./softmax";
import type { BaseCoefficients, ChoiceProbabilities, Plan, SegmentMultipliers } from "./types";

// Fixed, documented segment multipliers (Phase 3 spec) -- verbatim port of
// utility.py's SEGMENT_MULTIPLIERS. Any coefficient not listed for a segment
// implicitly multiplies by 1.0 (see `segmentCoefficients`). "mixed" -- the
// Phase 2 catch-all archetype segment -- and any other unrecognized segment
// name both resolve to the identity.
export const SEGMENT_MULTIPLIERS: Record<string, SegmentMultipliers> = {
  price_sensitive: { b_premium: 1.6, b_inertia: 0.6 },
  benefit_maximizer: { b_dental: 1.5, b_vision_hearing: 1.5, b_otc: 1.5 },
  brand_loyal: { b_inertia: 2.0 },
  health_status_driven: { b_star: 1.5, b_moop: 1.3 },
  mixed: {},
};

export const BASE_COEFFICIENT_NAMES: (keyof BaseCoefficients)[] = [
  "b_premium",
  "b_moop",
  "b_dental",
  "b_vision_hearing",
  "b_otc",
  "b_star",
  "b_ppo",
  "b_inertia",
  "b_outside",
];

export const STAR_RATING_CENTER = 3.5;
export const PREMIUM_DIVISOR = 10.0;
export const MOOP_DIVISOR = 1000.0;

/** Archetype-level coefficients: base * SEGMENT_MULTIPLIERS[segment] (default 1.0). */
export function segmentCoefficients(baseCoefficients: BaseCoefficients, segment: string): BaseCoefficients {
  const multipliers = SEGMENT_MULTIPLIERS[segment] ?? {};
  const result = {} as BaseCoefficients;
  for (const name of BASE_COEFFICIENT_NAMES) {
    const multiplier = multipliers[name] ?? 1.0;
    result[name] = baseCoefficients[name] * multiplier;
  }
  return result;
}

/** U(archetype, plan) for one already-scaled coefficient dict. */
export function planUtility(coefficients: BaseCoefficients, plan: Plan, priorProb: number): number {
  const star = plan.star_rating ?? STAR_RATING_CENTER; // neutral; plan attributes should already impute this.
  const isPpo = plan.is_ppo ? 1.0 : 0.0;
  const hasDental = plan.has_comprehensive_dental ? 1.0 : 0.0;
  const hasVision = plan.has_vision ? 1.0 : 0.0;
  const hasHearing = plan.has_hearing_aids ? 1.0 : 0.0;
  const hasOtc = plan.has_otc_or_flex ? 1.0 : 0.0;

  return (
    coefficients.b_premium * (plan.premium_total / PREMIUM_DIVISOR) +
    coefficients.b_moop * (plan.moop_inn / MOOP_DIVISOR) +
    coefficients.b_dental * hasDental +
    coefficients.b_vision_hearing * ((hasVision + hasHearing) / 2.0) +
    coefficients.b_otc * hasOtc +
    coefficients.b_star * (star - STAR_RATING_CENTER) +
    coefficients.b_ppo * isPpo +
    coefficients.b_inertia * priorProb
  );
}

/** U(archetype, outside) for one already-scaled coefficient dict. */
export function outsideUtility(coefficients: BaseCoefficients, priorProbOutside: number): number {
  return coefficients.b_outside + coefficients.b_inertia * priorProbOutside;
}

/**
 * Softmax choice probabilities over `plans` (already eligibility-filtered) + outside.
 *
 * `priorPlan` maps plan_key/outsideKey -> Year-1 prior probability (the
 * inertia term); a missing key defaults to 0.0. Returns plan_key/outsideKey
 * -> probability, summing to 1.0.
 */
export function choiceProbabilities(
  baseCoefficients: BaseCoefficients,
  segment: string,
  plans: Plan[],
  priorPlan: Record<string, number>,
  outsideKey: string,
): ChoiceProbabilities {
  const coefficients = segmentCoefficients(baseCoefficients, segment);

  const keys: string[] = [];
  const utilities: number[] = [];
  for (const plan of plans) {
    keys.push(plan.plan_key);
    utilities.push(planUtility(coefficients, plan, priorPlan[plan.plan_key] ?? 0.0));
  }
  keys.push(outsideKey);
  utilities.push(outsideUtility(coefficients, priorPlan[outsideKey] ?? 0.0));

  const probs = softmax(utilities);
  const result: ChoiceProbabilities = {};
  keys.forEach((key, i) => {
    result[key] = probs[i];
  });
  return result;
}
