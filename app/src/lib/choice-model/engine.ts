/**
 * Top-level choice-model engine: wires `choiceSets.ts` (eligibility +
 * prior-mass renormalization) and `utility.ts` (segment-scaled utility +
 * softmax) together into one call, mirroring the pipeline's actual usage
 * pattern (see `pipeline/choice_model/calibrate.py::predicted_2024_counts`
 * and `pipeline/tests/test_choice_model_choice_sets.py`'s end-to-end test):
 *
 *     eligible = eligiblePlans(archetype, plans)
 *     renormalizedPrior = renormalizePriorPlan(archetype.prior_plan_year1, archetype, plans, outsideKey)
 *     probs = choiceProbabilities(baseCoefficients, archetype.attitude_segment, eligible, renormalizedPrior, outsideKey)
 *
 * With default options, `archetypeChoiceProbabilities` reproduces that
 * pipeline exactly -- this is the function the Python <-> TS golden parity
 * fixture (`shared/golden/parity_fixture.json`, see
 * `app/tests/parity.test.ts`) is tested against.
 *
 * `opts` adds two extensions beyond the frozen Python module, for later
 * phases of this app (not part of the Python parity surface):
 *
 *   - `utilityDeltas`: an additive per-plan (and optionally per-outside)
 *     utility bonus/penalty, keyed by plan_key/outsideKey, default 0 for
 *     every key. Intended for injecting cached LLM-derived rank bonuses
 *     into the deterministic utility, without needing a second model.
 *   - `inertiaMultiplier`: a scalar applied on top of the segment-scaled
 *     `b_inertia`, default 1 (no-op). Lets a caller dial status-quo/
 *     switching-cost strength up or down for a scenario without re-fitting
 *     coefficients.
 */

import { eligiblePlans, renormalizePriorPlan } from "./choiceSets";
import { softmax } from "./softmax";
import type { Archetype, ChoiceProbabilities, CoefficientsFile, Plan } from "./types";
import { outsideUtility, planUtility, segmentCoefficients } from "./utility";

export interface ArchetypeChoiceOptions {
  /** plan_key/outsideKey -> additive utility delta. Missing keys default to 0. */
  utilityDeltas?: Record<string, number>;
  /** Multiplier applied to the segment-scaled b_inertia coefficient. Default 1 (no-op). */
  inertiaMultiplier?: number;
  /** Overrides `coefficients.outside_option_key` if provided. */
  outsideKey?: string;
}

/**
 * Full archetype -> plan choice-probability pipeline: eligibility filter,
 * prior-mass renormalization, segment-scaled utility, numerically stable
 * softmax. With `opts` omitted (or its defaults left as-is), this is
 * bit-for-bit the same pipeline `pipeline/choice_model/utility.py` +
 * `pipeline/choice_model/choice_sets.py` run for one archetype.
 */
export function archetypeChoiceProbabilities(
  archetype: Archetype,
  plans: Plan[],
  coefficients: CoefficientsFile,
  opts: ArchetypeChoiceOptions = {},
): ChoiceProbabilities {
  const outsideKey = opts.outsideKey ?? coefficients.outside_option_key;
  const utilityDeltas = opts.utilityDeltas ?? {};
  const inertiaMultiplier = opts.inertiaMultiplier ?? 1.0;

  const eligible = eligiblePlans(archetype, plans);
  const renormalizedPrior = renormalizePriorPlan(archetype.prior_plan_year1 ?? {}, archetype, plans, outsideKey);

  const segmentScaled = segmentCoefficients(coefficients.base_coefficients, archetype.attitude_segment);
  const scaledCoefficients = { ...segmentScaled, b_inertia: segmentScaled.b_inertia * inertiaMultiplier };

  const keys: string[] = [];
  const utilities: number[] = [];
  for (const plan of eligible) {
    const priorProb = renormalizedPrior[plan.plan_key] ?? 0.0;
    const delta = utilityDeltas[plan.plan_key] ?? 0.0;
    keys.push(plan.plan_key);
    utilities.push(planUtility(scaledCoefficients, plan, priorProb) + delta);
  }

  const outsidePriorProb = renormalizedPrior[outsideKey] ?? 0.0;
  const outsideDelta = utilityDeltas[outsideKey] ?? 0.0;
  keys.push(outsideKey);
  utilities.push(outsideUtility(scaledCoefficients, outsidePriorProb) + outsideDelta);

  const probs = softmax(utilities);
  const result: ChoiceProbabilities = {};
  keys.forEach((key, i) => {
    result[key] = probs[i];
  });
  return result;
}
