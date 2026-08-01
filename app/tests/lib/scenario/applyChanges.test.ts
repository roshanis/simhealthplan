import { describe, expect, it } from "vitest";

import type { Plan } from "@/lib/choice-model/types";
import { applyChangeToPlan, applyChanges } from "@/lib/scenario/applyChanges";
import type { ScenarioChange } from "@/lib/scenario/schema";

function makePlan(overrides: Partial<Plan> = {}): Plan {
  return {
    plan_key: "H0001-001",
    is_ppo: false,
    snp_type: "Not Applicable",
    premium_total: 20,
    moop_inn: 5000,
    star_rating: 4,
    has_comprehensive_dental: true,
    has_vision: true,
    has_hearing_aids: true,
    has_otc_or_flex: true,
    ...overrides,
  };
}

describe("applyChangeToPlan", () => {
  it("applies a numeric delta additively", () => {
    const result = applyChangeToPlan(makePlan({ premium_total: 20 }), {
      plan_key: "H0001-001",
      field: "premium_total",
      delta: -15,
    } as ScenarioChange);
    expect(result.premium_total).toBe(5);
  });

  it("applies a numeric set absolutely", () => {
    const result = applyChangeToPlan(makePlan({ premium_total: 20 }), {
      plan_key: "H0001-001",
      field: "premium_total",
      set: 0,
    } as ScenarioChange);
    expect(result.premium_total).toBe(0);
  });

  it("clamps premium_total at 0 (never negative)", () => {
    const result = applyChangeToPlan(makePlan({ premium_total: 5 }), {
      plan_key: "H0001-001",
      field: "premium_total",
      delta: -500,
    } as ScenarioChange);
    expect(result.premium_total).toBe(0);
  });

  it("clamps star_rating to [1, 5]", () => {
    const high = applyChangeToPlan(makePlan({ star_rating: 4.5 }), {
      plan_key: "H0001-001",
      field: "star_rating",
      delta: 3,
    } as ScenarioChange);
    expect(high.star_rating).toBe(5);

    const low = applyChangeToPlan(makePlan({ star_rating: 1.5 }), {
      plan_key: "H0001-001",
      field: "star_rating",
      delta: -5,
    } as ScenarioChange);
    expect(low.star_rating).toBe(1);
  });

  it("sets a boolean field", () => {
    const result = applyChangeToPlan(makePlan({ has_comprehensive_dental: true }), {
      plan_key: "H0001-001",
      field: "has_comprehensive_dental",
      set: false,
    } as ScenarioChange);
    expect(result.has_comprehensive_dental).toBe(false);
  });

  it("does not mutate the input plan", () => {
    const plan = makePlan({ premium_total: 20 });
    applyChangeToPlan(plan, { plan_key: "H0001-001", field: "premium_total", delta: -15 } as ScenarioChange);
    expect(plan.premium_total).toBe(20);
  });
});

describe("applyChanges", () => {
  const basePlans = [makePlan({ plan_key: "A", premium_total: 20 }), makePlan({ plan_key: "B", premium_total: 30 })];

  it("only mutates the targeted plan(s), leaving others byte-identical", () => {
    const { plans } = applyChanges(basePlans, [
      { plan_key: "A", field: "premium_total", delta: -5 } as ScenarioChange,
    ]);
    expect(plans.find((p) => p.plan_key === "A")?.premium_total).toBe(15);
    expect(plans.find((p) => p.plan_key === "B")).toBe(basePlans[1]); // same reference: untouched
  });

  it("applies multiple changes to the same plan in order", () => {
    const { plans, changedPlanKeys } = applyChanges(basePlans, [
      { plan_key: "A", field: "premium_total", delta: -5 } as ScenarioChange,
      { plan_key: "A", field: "has_comprehensive_dental", set: false } as ScenarioChange,
    ]);
    const planA = plans.find((p) => p.plan_key === "A")!;
    expect(planA.premium_total).toBe(15);
    expect(planA.has_comprehensive_dental).toBe(false);
    expect(changedPlanKeys).toEqual(["A"]);
  });

  it("never mutates basePlans itself", () => {
    const snapshot = JSON.stringify(basePlans);
    applyChanges(basePlans, [{ plan_key: "A", field: "premium_total", delta: -5 } as ScenarioChange]);
    expect(JSON.stringify(basePlans)).toBe(snapshot);
  });

  it("silently skips a change targeting an unknown plan_key", () => {
    const { plans, changedPlanKeys } = applyChanges(basePlans, [
      { plan_key: "NOPE", field: "premium_total", delta: -5 } as ScenarioChange,
    ]);
    expect(plans).toEqual(basePlans);
    expect(changedPlanKeys).toEqual(["NOPE"]);
  });
});
