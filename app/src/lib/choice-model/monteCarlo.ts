/**
 * Seeded Monte Carlo uncertainty bands for aggregate per-plan choice shares.
 *
 * NOT part of the Python <-> TypeScript parity surface (see
 * `app/tests/parity.test.ts`'s comment on this) -- this is a TS-only
 * addition on top of the ported deterministic core (`utility.ts` /
 * `choiceSets.ts` / `engine.ts`). Draws need not, and will not, match any
 * Python RNG output; only the deterministic core (`archetypeChoiceProbabilities`
 * and friends) is parity-tested.
 *
 * Each of `draws` independent samples:
 *
 *   1. Jitters the 9 base coefficients: for coefficient `b`,
 *      `b' ~ Normal(b, max(0.10 * |b|, 0.01))`, via a Box-Muller transform
 *      seeded from a `mulberry32` PRNG.
 *   2. Jitters each archetype's population `weight` log-normally
 *      (`weight' = weight * exp(Normal(0, 0.10))`), then renormalizes the
 *      jittered weights back to the archetypes' true total weight -- only
 *      the *relative* mix across archetypes varies draw-to-draw, not the
 *      modeled population's overall size. (For a single archetype this is
 *      a no-op: renormalizing one positive weight to the total always
 *      yields the original weight back.)
 *   3. Computes each archetype's choice probabilities under the jittered
 *      coefficients (`archetypeChoiceProbabilities`), then aggregates into
 *      one weighted per-plan/outside share for that draw.
 *
 * After all draws, returns each plan_key/outsideKey's p10/p50/p90 share
 * (linear-interpolated percentiles over the draw samples, sorted ascending).
 */

import { archetypeChoiceProbabilities, type ArchetypeChoiceOptions } from "./engine";
import type { Archetype, CoefficientsFile, Plan } from "./types";
import { BASE_COEFFICIENT_NAMES } from "./utility";
import type { BaseCoefficients } from "./types";

/** Deterministic 32-bit PRNG (public-domain "mulberry32"). Returns a
 * generator of floats in [0, 1). Same seed -> same sequence, always. */
export function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return function next(): number {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** One standard-normal sample via the Box-Muller transform, drawn from `rng`. */
export function sampleStandardNormal(rng: () => number): number {
  let u = 0;
  let v = 0;
  // rng() is in [0, 1); exclude exactly 0 from u to avoid log(0) = -Infinity.
  while (u === 0) u = rng();
  while (v === 0) v = rng();
  return Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
}

function jitterCoefficients(
  base: BaseCoefficients,
  rng: () => number,
  relativeSd: number,
  minSd: number,
): BaseCoefficients {
  const jittered = {} as BaseCoefficients;
  for (const name of BASE_COEFFICIENT_NAMES) {
    const b = base[name];
    const sd = Math.max(relativeSd * Math.abs(b), minSd);
    jittered[name] = b + sampleStandardNormal(rng) * sd;
  }
  return jittered;
}

function percentile(sortedAscending: number[], p: number): number {
  const n = sortedAscending.length;
  if (n === 0) return 0;
  if (n === 1) return sortedAscending[0];
  const rank = p * (n - 1);
  const lowerIndex = Math.floor(rank);
  const upperIndex = Math.ceil(rank);
  if (lowerIndex === upperIndex) return sortedAscending[lowerIndex];
  const frac = rank - lowerIndex;
  return sortedAscending[lowerIndex] * (1 - frac) + sortedAscending[upperIndex] * frac;
}

export interface MonteCarloBand {
  p10: number;
  p50: number;
  p90: number;
}

export interface MonteCarloOptions extends ArchetypeChoiceOptions {
  /** Number of independent draws. Default 200. */
  draws?: number;
  /** PRNG seed. Same seed (and same inputs) -> bit-for-bit same bands. Default 1. */
  seed?: number;
  /** Fraction of |b| used as each coefficient's jitter std-dev floor input. Default 0.10. */
  coefficientJitterRelativeSd?: number;
  /** Absolute floor on each coefficient's jitter std-dev. Default 0.01. */
  coefficientJitterMinSd?: number;
  /** Log-space std-dev for each archetype's log-normal weight jitter. Default 0.10. */
  weightJitterLogSd?: number;
}

/**
 * Monte Carlo p10/p50/p90 bands for each plan_key's (+ the outside option's)
 * aggregate, weight-blended choice share across `archetypes`.
 *
 * Deterministic given `opts.seed`: calling this twice with the same seed
 * (and the same archetypes/plans/coefficients/opts) always returns
 * identical bands.
 */
export function monteCarloShares(
  archetypes: Archetype[],
  plans: Plan[],
  coefficients: CoefficientsFile,
  opts: MonteCarloOptions = {},
): Record<string, MonteCarloBand> {
  const draws = opts.draws ?? 200;
  const seed = opts.seed ?? 1;
  const relativeSd = opts.coefficientJitterRelativeSd ?? 0.1;
  const minSd = opts.coefficientJitterMinSd ?? 0.01;
  const weightLogSd = opts.weightJitterLogSd ?? 0.1;
  const outsideKey = opts.outsideKey ?? coefficients.outside_option_key;

  const rng = mulberry32(seed);

  const baseWeights = archetypes.map((a) => a.weight ?? 1.0);
  const totalWeight = baseWeights.reduce((sum, w) => sum + w, 0) || 1.0;

  const allKeys = new Set<string>();
  for (const plan of plans) allKeys.add(plan.plan_key);
  allKeys.add(outsideKey);

  const samples: Record<string, number[]> = {};
  for (const key of allKeys) samples[key] = [];

  for (let draw = 0; draw < draws; draw++) {
    const jitteredCoefficients: CoefficientsFile = {
      ...coefficients,
      base_coefficients: jitterCoefficients(coefficients.base_coefficients, rng, relativeSd, minSd),
    };

    const jitteredWeights = baseWeights.map((w) => w * Math.exp(sampleStandardNormal(rng) * weightLogSd));
    const jitteredTotal = jitteredWeights.reduce((sum, w) => sum + w, 0) || 1.0;
    const normalizedWeights = jitteredWeights.map((w) => (w / jitteredTotal) * totalWeight);

    const drawShares: Record<string, number> = {};
    for (const key of allKeys) drawShares[key] = 0;

    archetypes.forEach((archetype, i) => {
      const probs = archetypeChoiceProbabilities(archetype, plans, jitteredCoefficients, opts);
      const weightShare = normalizedWeights[i] / totalWeight;
      for (const [key, prob] of Object.entries(probs)) {
        drawShares[key] = (drawShares[key] ?? 0) + weightShare * prob;
      }
    });

    for (const key of allKeys) {
      samples[key].push(drawShares[key] ?? 0);
    }
  }

  const result: Record<string, MonteCarloBand> = {};
  for (const key of allKeys) {
    const sorted = [...samples[key]].sort((a, b) => a - b);
    result[key] = {
      p10: percentile(sorted, 0.1),
      p50: percentile(sorted, 0.5),
      p90: percentile(sorted, 0.9),
    };
  }
  return result;
}
