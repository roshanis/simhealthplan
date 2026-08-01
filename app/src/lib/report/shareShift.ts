/**
 * Pure data-prep for the report's share-shift dot plot: turns
 * `backtest.json`'s `per_plan` rows into the top-N-by-2024-enrollment rows
 * (real plans only -- the outside option is excluded, see `isRealPlanRow`)
 * plus one aggregated "All other plans" row for everything past the top N.
 *
 * Kept separate from the chart component (`components/report/ShareShiftChart.tsx`)
 * so the row-selection/aggregation math is unit-testable without rendering.
 */

import type { BacktestSummary, NaiveVariant, PerPlanRow } from "@/lib/data/types";

export interface ShareShiftRow {
  key: string;
  label: string;
  org: string | null;
  enrollment2024: number;
  predictedPP: number;
  actualPP: number;
  bestNaivePP: number;
  isAggregate: boolean;
  aggregatedCount?: number;
}

export const OTHER_ROW_KEY = "__other_plans__";

/** True for a real plan row (excludes the outside/no-MA option, which
 * `per_plan` includes for backtest scoring but which isn't "a plan" for
 * this chart's roster-ranking purpose -- identified by `org === null`,
 * the one field `export_artifacts.build_backtest` can't populate for the
 * synthetic outside-option row). */
export function isRealPlanRow(row: PerPlanRow): boolean {
  return row.org !== null;
}

function naiveShareField(variant: NaiveVariant): "share_2025_naive_nochange" | "share_2025_naive_trend" {
  return variant === "no_change" ? "share_2025_naive_nochange" : "share_2025_naive_trend";
}

function toPP(after: number, before: number): number {
  return (after - before) * 100;
}

/**
 * Builds the chart's row set: the top `topN` real plans by `enrollment_2024`
 * descending (ties broken by `plan_key` for determinism), plus one
 * `isAggregate` row summing every remaining real plan's 2024/2025 shares
 * (so its pp shift is the correctly-weighted aggregate, not an average of
 * per-plan pp shifts). Rows are returned in display order: top plans by
 * enrollment descending, "All other plans" last.
 */
export function buildShareShiftRows(
  perPlan: PerPlanRow[],
  bestNaiveVariant: NaiveVariant,
  topN = 15,
): ShareShiftRow[] {
  const naiveField = naiveShareField(bestNaiveVariant);
  const realPlans = perPlan
    .filter(isRealPlanRow)
    .slice()
    .sort((a, b) => b.enrollment_2024 - a.enrollment_2024 || a.plan_key.localeCompare(b.plan_key));

  const top = realPlans.slice(0, topN);
  const rest = realPlans.slice(topN);

  const topRows: ShareShiftRow[] = top.map((row) => ({
    key: row.plan_key,
    label: row.name,
    org: row.org,
    enrollment2024: row.enrollment_2024,
    predictedPP: toPP(row.share_2025_pred_logit, row.share_2024),
    actualPP: toPP(row.share_2025_actual, row.share_2024),
    bestNaivePP: toPP(row[naiveField], row.share_2024),
    isAggregate: false,
  }));

  if (rest.length === 0) {
    return topRows;
  }

  const sums = rest.reduce(
    (acc, row) => ({
      enrollment2024: acc.enrollment2024 + row.enrollment_2024,
      share2024: acc.share2024 + row.share_2024,
      sharePredicted: acc.sharePredicted + row.share_2025_pred_logit,
      shareActual: acc.shareActual + row.share_2025_actual,
      shareNaive: acc.shareNaive + row[naiveField],
    }),
    { enrollment2024: 0, share2024: 0, sharePredicted: 0, shareActual: 0, shareNaive: 0 },
  );

  const otherRow: ShareShiftRow = {
    key: OTHER_ROW_KEY,
    label: "All other plans",
    org: null,
    enrollment2024: sums.enrollment2024,
    predictedPP: toPP(sums.sharePredicted, sums.share2024),
    actualPP: toPP(sums.shareActual, sums.share2024),
    bestNaivePP: toPP(sums.shareNaive, sums.share2024),
    isAggregate: true,
    aggregatedCount: rest.length,
  };

  return [...topRows, otherRow];
}

/** Symmetric domain (± pp) that comfortably fits every row's three values,
 * rounded up to a clean step so axis ticks land on round numbers. */
export function shareShiftDomain(rows: ShareShiftRow[], stepPp = 1): number {
  let max = 0;
  for (const row of rows) {
    max = Math.max(max, Math.abs(row.predictedPP), Math.abs(row.actualPP), Math.abs(row.bestNaivePP));
  }
  if (max === 0) return stepPp;
  return Math.ceil((max * 1.15) / stepPp) * stepPp;
}

/** The best-naive variant name from `backtest.json`'s summary, used to pick
 * which naive baseline the chart's reference tick represents. */
export function bestNaiveVariant(summary: BacktestSummary): NaiveVariant {
  return summary.best_naive.selected;
}
