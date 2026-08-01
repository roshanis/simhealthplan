import { describe, expect, it } from "vitest";

import type { PerPlanRow } from "@/lib/data/types";
import {
  OTHER_ROW_KEY,
  bestNaiveVariant,
  buildShareShiftRows,
  isRealPlanRow,
  shareShiftDomain,
} from "@/lib/report/shareShift";

function makeRow(overrides: Partial<PerPlanRow> = {}): PerPlanRow {
  return {
    plan_key: "H0000-001",
    name: "Test Plan",
    org: "Test Org",
    enrollment_2024: 1000,
    share_2024: 0.01,
    share_2025_actual: 0.01,
    share_2025_pred_logit: 0.01,
    share_2025_pred_blended: null,
    share_2025_naive_nochange: 0.01,
    share_2025_naive_trend: 0.01,
    abs_error_logit: 0,
    abs_error_blended: null,
    abs_error_naive_nochange: 0,
    abs_error_naive_trend: 0,
    ...overrides,
  };
}

describe("isRealPlanRow", () => {
  it("is true for a row with an org", () => {
    expect(isRealPlanRow(makeRow({ org: "Humana" }))).toBe(true);
  });

  it("is false for the synthetic outside-option row (org is null)", () => {
    expect(isRealPlanRow(makeRow({ org: null, plan_key: "other_or_no_ma_2025" }))).toBe(false);
  });
});

describe("bestNaiveVariant", () => {
  it("reads summary.best_naive.selected", () => {
    expect(
      bestNaiveVariant({
        best_naive: { selected: "no_change", weighted_mae: { no_change: 0.004, trend: 0.006 } },
        beats_naive: { logit: false, blended: null },
        directional_accuracy: { logit: 0.7, no_change: 0.4, trend: 0.6, blended: null },
        outside_share_error: { logit: 0.02, no_change: 0.01, trend: 0.04, blended: null },
        weighted_mae: { logit: 0.012, no_change: 0.004, trend: 0.006, blended: null },
      }),
    ).toBe("no_change");
  });
});

describe("buildShareShiftRows", () => {
  it("excludes the outside-option row entirely, even if it has the largest enrollment", () => {
    const rows: PerPlanRow[] = [
      makeRow({ plan_key: "other_or_no_ma_2025", org: null, enrollment_2024: 1_000_000 }),
      makeRow({ plan_key: "H0001-001", enrollment_2024: 500 }),
    ];
    const result = buildShareShiftRows(rows, "no_change", 15);
    expect(result.some((r) => r.key === "other_or_no_ma_2025")).toBe(false);
    expect(result).toHaveLength(1);
  });

  it("ranks real plans by 2024 enrollment descending", () => {
    const rows: PerPlanRow[] = [
      makeRow({ plan_key: "SMALL", enrollment_2024: 100 }),
      makeRow({ plan_key: "BIG", enrollment_2024: 900 }),
      makeRow({ plan_key: "MID", enrollment_2024: 500 }),
    ];
    const result = buildShareShiftRows(rows, "no_change", 15);
    expect(result.map((r) => r.key)).toEqual(["BIG", "MID", "SMALL"]);
  });

  it("aggregates everything past topN into one 'All other plans' row, summed not averaged", () => {
    const rows: PerPlanRow[] = [
      makeRow({ plan_key: "A", enrollment_2024: 300, share_2024: 0.10, share_2025_actual: 0.12 }),
      makeRow({ plan_key: "B", enrollment_2024: 200, share_2024: 0.05, share_2025_actual: 0.06 }),
      makeRow({ plan_key: "C", enrollment_2024: 100, share_2024: 0.02, share_2025_actual: 0.01 }),
    ];
    const result = buildShareShiftRows(rows, "no_change", 1);
    expect(result).toHaveLength(2);
    const other = result.find((r) => r.key === OTHER_ROW_KEY);
    expect(other).toBeDefined();
    expect(other!.isAggregate).toBe(true);
    expect(other!.aggregatedCount).toBe(2);
    // aggregated actual pp = (0.06+0.01 - (0.05+0.02)) * 100 = 0.0 pp
    expect(other!.actualPP).toBeCloseTo(0.0, 9);
    expect(other!.label).toBe("All other plans");
  });

  it("omits the aggregate row entirely when every real plan fits under topN", () => {
    const rows: PerPlanRow[] = [makeRow({ plan_key: "A" }), makeRow({ plan_key: "B" })];
    const result = buildShareShiftRows(rows, "no_change", 15);
    expect(result.some((r) => r.key === OTHER_ROW_KEY)).toBe(false);
  });

  it("uses the trend naive field when trend is the selected best-naive variant", () => {
    const rows: PerPlanRow[] = [
      makeRow({
        plan_key: "A",
        share_2024: 0.10,
        share_2025_naive_nochange: 0.10,
        share_2025_naive_trend: 0.15,
      }),
    ];
    const result = buildShareShiftRows(rows, "trend", 15);
    expect(result[0].bestNaivePP).toBeCloseTo(5.0, 9);
  });

  it("computes predicted/actual pp shift as (after - before) * 100", () => {
    const rows: PerPlanRow[] = [makeRow({ plan_key: "A", share_2024: 0.02, share_2025_pred_logit: 0.03 })];
    const result = buildShareShiftRows(rows, "no_change", 15);
    expect(result[0].predictedPP).toBeCloseTo(1.0, 9);
  });
});

describe("shareShiftDomain", () => {
  it("returns a symmetric domain covering the largest |value| across all three series, with headroom", () => {
    const rows = [
      { key: "a", label: "A", org: null, enrollment2024: 1, predictedPP: 5.3, actualPP: -0.2, bestNaivePP: 0.1, isAggregate: false },
    ];
    const domain = shareShiftDomain(rows, 1);
    expect(domain).toBeGreaterThanOrEqual(5.3 * 1.15);
    expect(domain % 1).toBe(0);
  });

  it("falls back to one step when every row is exactly zero", () => {
    const rows = [
      { key: "a", label: "A", org: null, enrollment2024: 1, predictedPP: 0, actualPP: 0, bestNaivePP: 0, isAggregate: false },
    ];
    expect(shareShiftDomain(rows, 2)).toBe(2);
  });
});
