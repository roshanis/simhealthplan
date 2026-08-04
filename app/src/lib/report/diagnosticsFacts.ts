/**
 * Pure view-model / derivation layer for the "Evaluation diagnostics" panel
 * (`components/report/DiagnosticsPanel.tsx`). Mirrors `marketFacts.ts` /
 * `shareShift.ts`'s discipline: every number the panel renders is computed
 * here, straight off the loaded `diagnostics.json`, so the displayed copy
 * can never drift out of sync with what the pipeline actually found. No
 * literal from the three findings (coverage, damping, error concentration)
 * is hardcoded in JSX -- if the diagnostics artifact is regenerated with a
 * different result, every figure and badge below updates with it.
 *
 * `diagnostics.json` already computes its own qualitative verdicts (e.g.
 * `coverage.verdict_unweighted`, `damping.verdict.oracle_beats_no_change_on_mae`)
 * -- the badge helpers below map THOSE fields to a `StatusBadge` status/label
 * rather than re-deriving the underlying threshold logic client-side, so a
 * future diagnostics rerun that flips a verdict can't silently desync this
 * panel's badge color from the pipeline's own conclusion.
 */

import { formatAbsPP, formatPercent } from "@/lib/format";
import type { Status } from "@/components/ui/StatusBadge";
import type {
  DiagnosticsDampingVerdict,
  DiagnosticsFile,
  DiagnosticsTopContributorRow,
} from "@/lib/data/types";

// --- Finding 1: confidence-band coverage --------------------------------------------

export interface CoverageFacts {
  nCovered: number;
  nEvaluated: number;
  nAbove: number;
  nBelow: number;
  nominalPct: string;
  unweightedCoveragePct: string;
  weightedCoveragePct: string;
  asymmetryNote: string;
  badge: { status: Status; label: string };
}

const COVERAGE_VERDICT_BADGE: Record<string, { status: Status; label: string }> = {
  too_narrow_overconfident: { status: "critical", label: "Bands too narrow (overconfident)" },
  too_wide_underconfident: { status: "warning", label: "Bands too wide (underconfident)" },
  well_calibrated: { status: "good", label: "Well calibrated" },
};

/** Maps `coverage.verdict_unweighted` to a badge; falls back to a muted
 * badge showing the raw verdict string for any value the pipeline might
 * emit that this panel doesn't yet have copy for, rather than throwing. */
export function coverageBadge(verdict: string): { status: Status; label: string } {
  return COVERAGE_VERDICT_BADGE[verdict] ?? { status: "muted", label: verdict };
}

export function buildCoverageFacts(diagnostics: DiagnosticsFile): CoverageFacts {
  const { coverage } = diagnostics;
  const { plan_level: planLevel } = coverage;
  return {
    nCovered: planLevel.n_covered,
    nEvaluated: planLevel.n_evaluated,
    nAbove: planLevel.n_above,
    nBelow: planLevel.n_below,
    nominalPct: formatPercent(coverage.nominal_coverage, 0),
    unweightedCoveragePct: formatPercent(planLevel.unweighted_coverage),
    weightedCoveragePct: formatPercent(planLevel.weighted_coverage),
    asymmetryNote: coverage.asymmetry_note,
    badge: coverageBadge(coverage.verdict_unweighted),
  };
}

// --- Finding 2: damping / shrinkage sweep -------------------------------------------

export interface DampingFacts {
  oracleLambda: number;
  oracleLambdaLabel: string;
  oracleWeightedMaePct: string;
  noChangeWeightedMaePct: string;
  lopoWeightedMaePct: string;
  lopoFoldsAtOracleLambda: number;
  lopoTotalFolds: number;
  lopoFoldsAtOracleLambdaPct: string;
  isDegenerate: boolean;
  summary: string;
  badge: { status: Status; label: string };
}

/** A lambda value formatted to match the grid's own precision (2 decimal
 * places, e.g. `0.15`), used both for display and as the key into
 * `chosen_lambda_distribution.counts` (which is itself keyed this way). */
export function formatLambda(lambda: number): string {
  return lambda.toFixed(2);
}

/** Degenerate iff the oracle lambda* rounds to the no-change endpoint
 * (0.00) -- i.e. the best damped predictor, chosen with the full benefit of
 * hindsight, simply IS the no-change baseline. Derived from the oracle
 * lambda value itself, not a hardcoded boolean, so this tracks whatever the
 * committed artifact actually found. */
export function isDegenerateShrinkage(oracleLambda: number): boolean {
  return formatLambda(oracleLambda) === "0.00";
}

export function dampingBadge(verdict: DiagnosticsDampingVerdict): { status: Status; label: string } {
  if (isDegenerateShrinkage(verdict.oracle_lambda)) {
    return { status: "critical", label: "No genuine improvement (λ*=0)" };
  }
  if (!verdict.lopo_cv_beats_no_change_on_mae) {
    return { status: "warning", label: "Doesn't beat baseline out-of-sample" };
  }
  return { status: "good", label: "Beats no-change baseline out-of-sample" };
}

export function buildDampingFacts(diagnostics: DiagnosticsFile): DampingFacts {
  const { damping } = diagnostics;
  const { oracle, leave_one_plan_out_cv: lopo, endpoints, verdict } = damping;

  const oracleLambdaKey = formatLambda(oracle.lambda);
  const foldsAtOracleLambda = lopo.chosen_lambda_distribution.counts[oracleLambdaKey] ?? 0;

  return {
    oracleLambda: oracle.lambda,
    oracleLambdaLabel: oracleLambdaKey,
    oracleWeightedMaePct: formatAbsPP(oracle.weighted_mae),
    noChangeWeightedMaePct: formatAbsPP(endpoints.lambda_0_is_no_change_baseline.weighted_mae),
    lopoWeightedMaePct: formatAbsPP(lopo.weighted_mae),
    lopoFoldsAtOracleLambda: foldsAtOracleLambda,
    lopoTotalFolds: lopo.chosen_lambda_distribution.n,
    lopoFoldsAtOracleLambdaPct: formatPercent(foldsAtOracleLambda / lopo.chosen_lambda_distribution.n, 0),
    isDegenerate: isDegenerateShrinkage(oracle.lambda),
    summary: verdict.summary,
    badge: dampingBadge(verdict),
  };
}

// --- Finding 3: error concentration -------------------------------------------------

export interface ErrorConcentrationFacts {
  topContributor: DiagnosticsTopContributorRow;
  topContributorSharePct: string;
  topContributorPredictedPct: string;
  topContributorActualPct: string;
  topContributorPrior2024Pct: string;
  nPlansTo80Pct: number;
  nPlansTo50Pct: number;
  nPlansScored: number;
  newEntrantCount: number;
  newEntrantNote: string;
  incumbentCount: number;
  badge: { status: Status; label: string };
}

/** Concentration is flagged "critical" whenever fewer than a quarter of
 * scored plans account for 80% of the published weighted error -- i.e. the
 * headline MAE is a story about a handful of plans, not a diffuse spread
 * across the market. Threshold is documented here, not buried in JSX. */
export function errorConcentrationBadge(nPlansTo80Pct: number, nPlansScored: number): { status: Status; label: string } {
  const ratio = nPlansScored > 0 ? nPlansTo80Pct / nPlansScored : 0;
  if (ratio <= 0.25) return { status: "critical", label: "Highly concentrated" };
  if (ratio <= 0.5) return { status: "warning", label: "Moderately concentrated" };
  return { status: "good", label: "Diffuse across plans" };
}

export function buildErrorConcentrationFacts(diagnostics: DiagnosticsFile): ErrorConcentrationFacts {
  const { error_decomposition: decomp } = diagnostics;
  const top = decomp.top_contributors[0];
  if (!top) {
    throw new Error("diagnostics.json error_decomposition.top_contributors is empty");
  }
  const { new_entrants: newEntrants, incumbents } = decomp.new_entrant_vs_incumbent_split;

  return {
    topContributor: top,
    // `top_contributors` is sorted by contribution descending with a running
    // cumulative share, so the first row's own cumulative_share_of_total IS
    // its individual share of the total weighted MAE.
    topContributorSharePct: formatPercent(top.cumulative_share_of_total),
    topContributorPredictedPct: formatPercent(top.share_2025_pred_logit),
    topContributorActualPct: formatPercent(top.share_2025_actual),
    topContributorPrior2024Pct: formatPercent(top.share_2024),
    nPlansTo80Pct: decomp.n_plans_to_reach_cumulative_share["80pct"],
    nPlansTo50Pct: decomp.n_plans_to_reach_cumulative_share["50pct"],
    nPlansScored: decomp.n_plans_scored,
    newEntrantCount: newEntrants.n_plans,
    newEntrantNote: decomp.new_entrant_vs_incumbent_split.note,
    incumbentCount: incumbents.n_plans,
    badge: errorConcentrationBadge(decomp.n_plans_to_reach_cumulative_share["80pct"], decomp.n_plans_scored),
  };
}

// --- shared: lambda-sweep chart data prep -------------------------------------------

export interface LambdaSweepPoint {
  lambda: number;
  lambdaLabel: string;
  weightedMae: number;
  weightedMaePct: string;
  directionalAccuracy: number;
  directionalAccuracyPct: string;
  isOracle: boolean;
}

/** Row-level view model for `DiagnosticsLambdaSweepChart`, built from
 * `damping.sweep` (kept separate from the component so the chart's own data
 * prep is unit-testable without rendering, matching `shareShift.ts`'s
 * `buildShareShiftRows` pattern). */
export function buildLambdaSweepPoints(diagnostics: DiagnosticsFile): LambdaSweepPoint[] {
  const oracleLambdaKey = formatLambda(diagnostics.damping.oracle.lambda);
  return diagnostics.damping.sweep.map((point) => ({
    lambda: point.lambda,
    lambdaLabel: formatLambda(point.lambda),
    weightedMae: point.weighted_mae,
    weightedMaePct: formatAbsPP(point.weighted_mae),
    directionalAccuracy: point.directional_accuracy,
    directionalAccuracyPct: formatPercent(point.directional_accuracy),
    isOracle: formatLambda(point.lambda) === oracleLambdaKey,
  }));
}

/** Y-axis domain (max weighted MAE across the sweep, rounded up 10% for
 * headroom) shared between the chart's SVG y-scale and its axis ticks. */
export function lambdaSweepMaeDomain(points: LambdaSweepPoint[]): number {
  const max = points.reduce((acc, p) => Math.max(acc, p.weightedMae), 0);
  return max === 0 ? 0.01 : max * 1.1;
}
