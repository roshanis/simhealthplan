import { describe, expect, it } from "vitest";

import type { Archetype, CoefficientsFile, Plan } from "@/lib/choice-model/types";
import { aggregateWeightedShares, runScenario } from "@/lib/scenario/runScenario";
import type { ScenarioChange } from "@/lib/scenario/schema";

const OUTSIDE_KEY = "outside_2025";

function makePlan(overrides: Partial<Plan> = {}): Plan {
  return {
    plan_key: "A",
    is_ppo: false,
    snp_type: "Not Applicable",
    premium_total: 20,
    moop_inn: 5000,
    star_rating: 4,
    has_comprehensive_dental: true,
    has_vision: true,
    has_hearing_aids: true,
    has_otc_or_flex: true,
    org_name: "Org",
    plan_name: "Plan",
    ...overrides,
  };
}

function makeArchetype(overrides: Partial<Archetype> = {}): Archetype {
  return {
    id: "arch-1",
    age_band: "70-74",
    attitude_segment: "mixed",
    dual_proxy: false,
    weight: 100,
    prior_plan_year1: { A: 0.3, B: 0.3, [OUTSIDE_KEY]: 0.4 },
    ...overrides,
  };
}

const COEFFICIENTS: CoefficientsFile = {
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

describe("aggregateWeightedShares", () => {
  it("weight-blends multiple archetypes and sums to 1", () => {
    const plans = [makePlan({ plan_key: "A" }), makePlan({ plan_key: "B", premium_total: 40 })];
    const archetypes = [
      makeArchetype({ id: "1", weight: 100 }),
      makeArchetype({ id: "2", weight: 300, prior_plan_year1: { A: 0.1, B: 0.5, [OUTSIDE_KEY]: 0.4 } }),
    ];
    const shares = aggregateWeightedShares(archetypes, plans, COEFFICIENTS, OUTSIDE_KEY);
    const total = Object.values(shares).reduce((s, v) => s + v, 0);
    expect(total).toBeCloseTo(1.0, 9);
  });

  it("regression guard: an outsideOptionKey that doesn't match the archetypes' prior_plan_year1 key silently drops that mass as ineligible, inflating real-plan shares -- this is exactly the scenario_inputs.json 2024-vs-2025 outside-key bug this function must never reintroduce", () => {
    const plans = [makePlan({ plan_key: "A" })];
    // Heavy inertia + most prior mass sitting on the (correctly named)
    // outside option -- mirrors a real archetype's shape.
    const heavyInertiaCoefficients: CoefficientsFile = {
      ...COEFFICIENTS,
      base_coefficients: { ...COEFFICIENTS.base_coefficients, b_inertia: 37.0 },
    };
    const archetypes = [
      makeArchetype({ id: "1", weight: 100, prior_plan_year1: { A: 0.05, [OUTSIDE_KEY]: 0.95 } }),
    ];

    const correct = aggregateWeightedShares(archetypes, plans, heavyInertiaCoefficients, OUTSIDE_KEY);
    const wrong = aggregateWeightedShares(archetypes, plans, heavyInertiaCoefficients, "some_other_outside_key_2024");

    // With the correct key, the outside option (holding 95% of prior mass
    // under strong inertia) should dominate -- plan A's share should be
    // small. With the wrong key, that 95% mass is dropped as "ineligible",
    // so A gets renormalized to ~100% prior mass and its share balloons.
    expect(correct.A).toBeLessThan(0.5);
    expect(wrong.A).toBeGreaterThan(correct.A);
  });
});

describe("runScenario", () => {
  const plans = [
    makePlan({ plan_key: "A", premium_total: 20, org_name: "Acme", plan_name: "Acme A" }),
    makePlan({ plan_key: "B", premium_total: 25, org_name: "Beta", plan_name: "Beta B" }),
  ];
  const archetypes = [makeArchetype({ weight: 1000 })];

  it("cutting a plan's premium increases its scenario share vs baseline", () => {
    const changes: ScenarioChange[] = [{ plan_key: "A", field: "premium_total", delta: -15 } as ScenarioChange];
    const result = runScenario(archetypes, plans, COEFFICIENTS, changes, OUTSIDE_KEY, { draws: 20, seed: 1 });

    expect(result.scenario.shares.A).toBeGreaterThan(result.baseline.shares.A);
    expect(result.changed_plan_keys).toEqual(["A"]);
    expect(result.affected).toHaveLength(1);
    expect(result.affected[0].delta_pp).toBeGreaterThan(0);
  });

  it("scenario bounds bracket (or sit very close to) the scenario point share for the changed plan", () => {
    const changes: ScenarioChange[] = [{ plan_key: "A", field: "premium_total", delta: -15 } as ScenarioChange];
    const result = runScenario(archetypes, plans, COEFFICIENTS, changes, OUTSIDE_KEY, { draws: 300, seed: 7 });
    const band = result.scenario.bounds.A;
    expect(band.p10).toBeLessThanOrEqual(band.p50);
    expect(band.p50).toBeLessThanOrEqual(band.p90);
    // the point estimate (unjittered coefficients) should land close to the
    // jittered median, and comfortably inside a modestly widened band
    const spread = band.p90 - band.p10;
    expect(result.scenario.shares.A).toBeGreaterThanOrEqual(band.p10 - spread * 0.5);
    expect(result.scenario.shares.A).toBeLessThanOrEqual(band.p90 + spread * 0.5);
  });

  it("top_movers excludes directly-changed plans and is sorted by |delta_pp| descending", () => {
    const threePlans = [...plans, makePlan({ plan_key: "C", premium_total: 30, org_name: "Gamma", plan_name: "Gamma C" })];
    const changes: ScenarioChange[] = [{ plan_key: "A", field: "premium_total", delta: -15 } as ScenarioChange];
    const result = runScenario(archetypes, threePlans, COEFFICIENTS, changes, OUTSIDE_KEY, { draws: 10, seed: 1 });

    expect(result.top_movers.some((m) => m.plan_key === "A")).toBe(false);
    for (let i = 1; i < result.top_movers.length; i++) {
      expect(Math.abs(result.top_movers[i - 1].delta_pp)).toBeGreaterThanOrEqual(Math.abs(result.top_movers[i].delta_pp));
    }
  });

  it("toggling dental off decreases a plan's share when b_dental > 0", () => {
    const changes: ScenarioChange[] = [{ plan_key: "A", field: "has_comprehensive_dental", set: false } as ScenarioChange];
    const result = runScenario(archetypes, plans, COEFFICIENTS, changes, OUTSIDE_KEY, { draws: 10, seed: 1 });
    expect(result.scenario.shares.A).toBeLessThan(result.baseline.shares.A);
  });

  it("with zero changes affecting a plan not in the roster, baseline === scenario", () => {
    const changes: ScenarioChange[] = [{ plan_key: "NOT-IN-ROSTER", field: "premium_total", delta: -5 } as ScenarioChange];
    const result = runScenario(archetypes, plans, COEFFICIENTS, changes, OUTSIDE_KEY, { draws: 10, seed: 1 });
    expect(result.scenario.shares).toEqual(result.baseline.shares);
  });
});
