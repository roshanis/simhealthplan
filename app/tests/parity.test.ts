import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { eligiblePlans, isEligible } from "@/lib/choice-model/choiceSets";
import { archetypeChoiceProbabilities } from "@/lib/choice-model/engine";
import { mulberry32, monteCarloShares, sampleStandardNormal } from "@/lib/choice-model/monteCarlo";
import { softmax } from "@/lib/choice-model/softmax";
import type { Archetype, CoefficientsFile, Plan } from "@/lib/choice-model/types";

// --- golden fixture loading -------------------------------------------------------

interface GoldenCase {
  case_id: string;
  kind: "real" | "synthetic" | "scenario";
  description: string;
  archetype: Archetype;
  plan_patches: Record<string, Partial<Plan>>;
  plan_subset: string[] | null;
  expected_probabilities: Record<string, number>;
}

interface GoldenFixture {
  metadata: {
    outside_option_key: string;
    n_cases: number;
    n_plans: number;
    comparison_tolerance: {
      typescript_relative_tolerance: number;
      typescript_absolute_floor: number;
    };
  };
  base_coefficients: CoefficientsFile["base_coefficients"];
  plans: Plan[];
  cases: GoldenCase[];
}

const fixturePath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "shared",
  "golden",
  "parity_fixture.json",
);

const fixture: GoldenFixture = JSON.parse(readFileSync(fixturePath, "utf-8"));

const coefficients: CoefficientsFile = {
  base_coefficients: fixture.base_coefficients,
  outside_option_key: fixture.metadata.outside_option_key,
};

/** Derive a golden case's actual plan list from the fixture's pristine
 * top-level `plans` array, exactly as `pipeline/export/golden_fixture.py`'s
 * `resolve_case_plans` (and its byte-identical replay in
 * `pipeline/tests/test_golden_parity.py`) do: patch, then (optionally)
 * subset. This mirrored derivation IS part of the parity contract. */
function resolveCasePlans(kase: GoldenCase): Plan[] {
  let plans = fixture.plans.map((plan) => {
    const patch = kase.plan_patches[plan.plan_key];
    return patch ? { ...plan, ...patch } : plan;
  });
  if (kase.plan_subset !== null) {
    const subset = new Set(kase.plan_subset);
    plans = plans.filter((plan) => subset.has(plan.plan_key));
  }
  return plans;
}

const RELATIVE_TOLERANCE = fixture.metadata.comparison_tolerance.typescript_relative_tolerance; // 1e-9
const ABSOLUTE_FLOOR = fixture.metadata.comparison_tolerance.typescript_absolute_floor; // 1e-12

function assertCloseWithRelativeTolerance(actual: number, expected: number, message: string): void {
  const allowed = Math.max(RELATIVE_TOLERANCE * Math.abs(expected), ABSOLUTE_FLOOR);
  const diff = Math.abs(actual - expected);
  expect(diff, `${message}: |${actual} - ${expected}| = ${diff} exceeds allowed ${allowed}`).toBeLessThanOrEqual(
    allowed,
  );
}

// --- golden parity: every fixture case ---------------------------------------------

describe("Python <-> TS choice-model golden parity", () => {
  it("fixture has the expected inventory (12 real + 3 synthetic + 2 scenario = 17 cases)", () => {
    expect(fixture.cases.length).toBe(17);
    expect(fixture.metadata.n_cases).toBe(17);
    const kinds = fixture.cases.map((c) => c.kind);
    expect(kinds.filter((k) => k === "real").length).toBe(12);
    expect(kinds.filter((k) => k === "synthetic").length).toBe(3);
    expect(kinds.filter((k) => k === "scenario").length).toBe(2);
  });

  for (const kase of fixture.cases) {
    it(`reproduces Python's expected probabilities for case: ${kase.case_id}`, () => {
      const plans = resolveCasePlans(kase);
      const actual = archetypeChoiceProbabilities(kase.archetype, plans, coefficients);
      const expected = kase.expected_probabilities;

      const actualKeys = Object.keys(actual).sort();
      const expectedKeys = Object.keys(expected).sort();
      expect(actualKeys).toEqual(expectedKeys);

      for (const key of expectedKeys) {
        assertCloseWithRelativeTolerance(actual[key], expected[key], `${kase.case_id} / ${key}`);
      }
    });
  }
});

// --- unit tests: core engine properties ---------------------------------------------

const OUTSIDE_KEY = "other_or_no_ma_2024";

function makePlan(key: string, overrides: Partial<Plan> = {}): Plan {
  return {
    plan_key: key,
    snp_type: "Not Applicable",
    is_ppo: false,
    premium_total: 20.0,
    moop_inn: 5000.0,
    has_comprehensive_dental: true,
    has_vision: true,
    has_hearing_aids: false,
    has_otc_or_flex: true,
    star_rating: 4.0,
    ...overrides,
  };
}

function makeArchetype(overrides: Partial<Archetype> = {}): Archetype {
  return {
    id: "test-archetype",
    age_band: "70-74",
    attitude_segment: "mixed",
    dual_proxy: false,
    prior_plan_year1: {},
    ...overrides,
  };
}

const TEST_COEFFICIENTS: CoefficientsFile = {
  base_coefficients: {
    b_premium: -0.2,
    b_moop: -0.15,
    b_dental: 0.3,
    b_vision_hearing: 0.25,
    b_otc: 0.2,
    b_star: 0.4,
    b_ppo: 0.1,
    b_inertia: 4.0,
    b_outside: -1.0,
  },
  outside_option_key: OUTSIDE_KEY,
};

describe("archetypeChoiceProbabilities: core properties", () => {
  it("probabilities sum to 1", () => {
    const plans = [makePlan("P1"), makePlan("P2", { premium_total: 30 }), makePlan("P3", { premium_total: 10 })];
    const archetype = makeArchetype({ prior_plan_year1: { P1: 0.2, P2: 0.2, [OUTSIDE_KEY]: 0.6 } });
    const probs = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS);
    const total = Object.values(probs).reduce((sum, p) => sum + p, 0);
    expect(total).toBeCloseTo(1.0, 9);
  });

  it("an ineligible plan gets exactly zero probability (it's excluded from the result entirely)", () => {
    const dsnpPlan = makePlan("DSNP", { snp_type: "Dual-Eligible" });
    const openPlan = makePlan("OPEN");
    const archetype = makeArchetype({ dual_proxy: false, prior_plan_year1: { DSNP: 0.5, OPEN: 0.3, [OUTSIDE_KEY]: 0.2 } });

    expect(isEligible(archetype, dsnpPlan)).toBe(false);
    expect(eligiblePlans(archetype, [dsnpPlan, openPlan])).toEqual([openPlan]);

    const probs = archetypeChoiceProbabilities(archetype, [dsnpPlan, openPlan], TEST_COEFFICIENTS);
    expect(probs.DSNP).toBeUndefined();
    expect(probs.DSNP ?? 0).toBe(0);
    const total = Object.values(probs).reduce((sum, p) => sum + p, 0);
    expect(total).toBeCloseTo(1.0, 9);
  });

  it("lowering a plan's premium strictly increases its probability (premium monotonicity)", () => {
    const plans = [makePlan("A", { premium_total: 50 }), makePlan("B", { premium_total: 20 })];
    const archetype = makeArchetype({ prior_plan_year1: { A: 0.3, B: 0.3, [OUTSIDE_KEY]: 0.4 } });
    const before = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS);

    const cheaperPlans = [makePlan("A", { premium_total: 10 }), makePlan("B", { premium_total: 20 })];
    const after = archetypeChoiceProbabilities(archetype, cheaperPlans, TEST_COEFFICIENTS);

    expect(after.A).toBeGreaterThan(before.A);
  });

  it("raising a plan's premium strictly decreases its probability", () => {
    const plans = [makePlan("A", { premium_total: 20 }), makePlan("B", { premium_total: 20 })];
    const archetype = makeArchetype({ prior_plan_year1: { A: 0.3, B: 0.3, [OUTSIDE_KEY]: 0.4 } });
    const before = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS);

    const pricierPlans = [makePlan("A", { premium_total: 80 }), makePlan("B", { premium_total: 20 })];
    const after = archetypeChoiceProbabilities(archetype, pricierPlans, TEST_COEFFICIENTS);

    expect(after.A).toBeLessThan(before.A);
  });

  it("injecting a positive utility delta on a plan strictly shifts its probability up", () => {
    const plans = [makePlan("A"), makePlan("B")];
    const archetype = makeArchetype({ prior_plan_year1: { A: 0.3, B: 0.3, [OUTSIDE_KEY]: 0.4 } });
    const before = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS);
    const after = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS, {
      utilityDeltas: { A: 2.0 },
    });

    expect(after.A).toBeGreaterThan(before.A);
    // sums still normalize to 1 with the delta applied
    expect(Object.values(after).reduce((s, p) => s + p, 0)).toBeCloseTo(1.0, 9);
  });

  it("default utilityDeltas (omitted) is a no-op vs. explicit all-zero deltas", () => {
    const plans = [makePlan("A"), makePlan("B")];
    const archetype = makeArchetype({ prior_plan_year1: { A: 0.3, B: 0.3, [OUTSIDE_KEY]: 0.4 } });
    const implicit = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS);
    const explicitZero = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS, {
      utilityDeltas: { A: 0, B: 0, [OUTSIDE_KEY]: 0 },
    });
    expect(implicit).toEqual(explicitZero);
  });

  it("a higher inertia multiplier widens the gap in favor of the plan already holding the prior mass", () => {
    const incumbent = makePlan("INCUMBENT");
    const challenger = makePlan("CHALLENGER");
    const plans = [incumbent, challenger];
    const archetype = makeArchetype({ prior_plan_year1: { INCUMBENT: 0.7, CHALLENGER: 0.1, [OUTSIDE_KEY]: 0.2 } });

    const normal = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS, { inertiaMultiplier: 1.0 });
    const amplified = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS, { inertiaMultiplier: 3.0 });

    const normalGap = normal.INCUMBENT - normal.CHALLENGER;
    const amplifiedGap = amplified.INCUMBENT - amplified.CHALLENGER;
    expect(amplifiedGap).toBeGreaterThan(normalGap);
  });

  it("inertiaMultiplier of 1 (default) matches the multiplier being omitted entirely", () => {
    const plans = [makePlan("A"), makePlan("B")];
    const archetype = makeArchetype({ prior_plan_year1: { A: 0.4, B: 0.2, [OUTSIDE_KEY]: 0.4 } });
    const implicit = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS);
    const explicit = archetypeChoiceProbabilities(archetype, plans, TEST_COEFFICIENTS, { inertiaMultiplier: 1.0 });
    expect(implicit).toEqual(explicit);
  });
});

describe("softmax", () => {
  it("is shift-invariant and sums to 1 (numerically stable max-subtraction)", () => {
    const utilities = [1000.0, 1002.0, 998.0];
    const probs = softmax(utilities);
    expect(probs.every((p) => Number.isFinite(p))).toBe(true);
    expect(probs.reduce((s, p) => s + p, 0)).toBeCloseTo(1.0, 12);
  });
});

// --- unit tests: seeded Monte Carlo ---------------------------------------------------

describe("monteCarloShares", () => {
  const mcPlans = [makePlan("A", { premium_total: 20 }), makePlan("B", { premium_total: 40 })];
  const mcArchetype = makeArchetype({
    id: "mc-archetype",
    weight: 100,
    prior_plan_year1: { A: 0.3, B: 0.2, [OUTSIDE_KEY]: 0.5 },
  });

  it("same seed -> bit-for-bit identical bands", () => {
    const first = monteCarloShares([mcArchetype], mcPlans, TEST_COEFFICIENTS, { seed: 7, draws: 100 });
    const second = monteCarloShares([mcArchetype], mcPlans, TEST_COEFFICIENTS, { seed: 7, draws: 100 });
    expect(second).toEqual(first);
  });

  it("different seeds can produce different bands", () => {
    const first = monteCarloShares([mcArchetype], mcPlans, TEST_COEFFICIENTS, { seed: 1, draws: 100 });
    const second = monteCarloShares([mcArchetype], mcPlans, TEST_COEFFICIENTS, { seed: 2, draws: 100 });
    expect(second).not.toEqual(first);
  });

  it("p10 <= p50 <= p90 for every plan and the outside option", () => {
    const bands = monteCarloShares([mcArchetype], mcPlans, TEST_COEFFICIENTS, { seed: 42, draws: 150 });
    for (const [key, band] of Object.entries(bands)) {
      expect(band.p10, key).toBeLessThanOrEqual(band.p50);
      expect(band.p50, key).toBeLessThanOrEqual(band.p90);
    }
    expect(Object.keys(bands).sort()).toEqual(["A", "B", OUTSIDE_KEY].sort());
  });

  it("mulberry32 is a deterministic, seed-dependent PRNG in [0, 1)", () => {
    const rngA = mulberry32(123);
    const rngB = mulberry32(123);
    const seqA = Array.from({ length: 5 }, () => rngA());
    const seqB = Array.from({ length: 5 }, () => rngB());
    expect(seqA).toEqual(seqB);
    for (const value of seqA) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(1);
    }
  });

  it("sampleStandardNormal produces finite values from a seeded rng", () => {
    const rng = mulberry32(99);
    for (let i = 0; i < 20; i++) {
      expect(Number.isFinite(sampleStandardNormal(rng))).toBe(true);
    }
  });
});
