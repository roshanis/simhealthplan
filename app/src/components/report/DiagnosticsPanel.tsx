/**
 * "Evaluation diagnostics" -- the pipeline's post-hoc scoring diagnostics
 * (`pipeline/backtest/diagnostics.py`, `make diagnostics` + `make
 * export-diagnostics`), surfaced in full rather than left in a JSON file
 * nobody outside the pipeline ever opens. Three findings, all unflattering,
 * rendered exactly as computed:
 *
 *   1. The nominal 80% p10-p90 Monte Carlo interval covers far fewer than
 *      80% of plans, and the misses are asymmetric (mostly above p90) --
 *      evidence of upward BIAS in the point estimate, not just
 *      underestimated variance. This is the same interval the backtest
 *      section elsewhere on this page displays; this panel exists so a
 *      reader never mistakes it for a trustworthy 80% band.
 *   2. Damping the choice-model prediction toward the no-change baseline
 *      picks an in-sample oracle lambda* of 0.00 -- the "best" damped
 *      predictor simply IS the no-change baseline, a degenerate result, not
 *      a real improvement. The honest, leave-one-plan-out cross-validated
 *      estimate is reported and labelled separately, and is never allowed
 *      to be confused with the in-sample oracle number.
 *   3. The published size-weighted MAE is dominated by a single plan. Four
 *      plans reach 80% of all error. New-entrant plans contribute exactly
 *      zero to the weighted metric by construction (no 2024 enrollment, so
 *      no weight) -- a documented blind spot of the metric, not evidence of
 *      accuracy for that group.
 *
 * Every number below is read off `diagnostics.json` via
 * `lib/report/diagnosticsFacts.ts` -- nothing here is a literal typed into
 * JSX, so a regenerated diagnostics artifact with different findings
 * updates this panel automatically instead of silently going stale.
 */

import { DiagnosticsLambdaSweepChart } from "@/components/report/DiagnosticsLambdaSweepChart";
import { MiniBarCompare } from "@/components/ui/MiniBarCompare";
import { StatTile } from "@/components/ui/StatTile";
import { formatAbsPP, formatCount, formatPercent } from "@/lib/format";
import {
  buildCoverageFacts,
  buildDampingFacts,
  buildErrorConcentrationFacts,
  buildLambdaSweepPoints,
  lambdaSweepMaeDomain,
} from "@/lib/report/diagnosticsFacts";
import type { DiagnosticsFile } from "@/lib/data/types";

export function DiagnosticsPanel({ diagnostics }: { diagnostics: DiagnosticsFile }) {
  const coverage = buildCoverageFacts(diagnostics);
  const damping = buildDampingFacts(diagnostics);
  const errorConcentration = buildErrorConcentrationFacts(diagnostics);
  const sweepPoints = buildLambdaSweepPoints(diagnostics);
  const maeDomain = lambdaSweepMaeDomain(sweepPoints);
  const topContributors = diagnostics.error_decomposition.top_contributors;

  // Bar-chart scale must fit all three coverage values, not just the nominal
  // target -- if a future rerun ever showed OVER-coverage the actual bar
  // could exceed the nominal one.
  const coverageBarMax = Math.max(
    diagnostics.coverage.nominal_coverage,
    diagnostics.coverage.plan_level.unweighted_coverage,
    diagnostics.coverage.plan_level.weighted_coverage,
  );

  return (
    <section aria-labelledby="diagnostics-heading" className="flex flex-col gap-10">
      <div className="flex flex-col gap-2">
        <h2 id="diagnostics-heading" className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
          Evaluation diagnostics: how far to trust the numbers above
        </h2>
        <p className="max-w-3xl text-base" style={{ color: "var(--text-secondary)" }}>
          Three post-hoc checks the pipeline runs against its own backtest, none of them
          flattering. Reported in full because the deliverable here is a rigorous evaluation,
          not a rigorous-looking one -- a negative result stated clearly is the point.
        </p>
      </div>

      {/* --- Finding 1: coverage --------------------------------------------------- */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h3 id="diagnostics-coverage-heading" className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
            1. The confidence bands are overconfident
          </h3>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            The p10-p90 Monte Carlo interval shown throughout this report is a nominal{" "}
            {coverage.nominalPct} interval: if it were well calibrated, roughly {coverage.nominalPct}{" "}
            of plans&rsquo; actual 2025 share should land inside it. Only {coverage.nCovered} of{" "}
            {coverage.nEvaluated} plans did ({coverage.unweightedCoveragePct} unweighted,{" "}
            {coverage.weightedCoveragePct} enrollment-weighted) -- treat the bands as directional
            sensitivity, not a trustworthy confidence interval at their stated level.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatTile
            label={`p10-p90 coverage vs nominal ${coverage.nominalPct}`}
            value={coverage.unweightedCoveragePct}
            status={coverage.badge}
            caption={`${coverage.nCovered} of ${coverage.nEvaluated} plans, unweighted.`}
          >
            <MiniBarCompare
              maxValue={coverageBarMax}
              rows={[
                {
                  key: "nominal",
                  label: `Nominal (${coverage.nominalPct})`,
                  value: diagnostics.coverage.nominal_coverage,
                  valueLabel: coverage.nominalPct,
                },
                {
                  key: "actual-unweighted",
                  label: "Actual (unweighted)",
                  value: diagnostics.coverage.plan_level.unweighted_coverage,
                  valueLabel: coverage.unweightedCoveragePct,
                  emphasize: true,
                },
                {
                  key: "actual-weighted",
                  label: "Actual (weighted)",
                  value: diagnostics.coverage.plan_level.weighted_coverage,
                  valueLabel: coverage.weightedCoveragePct,
                },
              ]}
            />
          </StatTile>

          <StatTile
            label="Enrollment-weighted coverage"
            value={coverage.weightedCoveragePct}
            status={coverage.badge}
            caption="Weighting by 2024 enrollment still falls well short of the nominal interval -- this isn't an artifact of many small, noisy plans."
          />

          <StatTile
            label="Miss direction"
            value={`${coverage.nAbove} above / ${coverage.nBelow} below`}
            status={{ status: "warning", label: "Asymmetric misses" }}
            caption={coverage.asymmetryNote}
          />
        </div>
      </div>

      {/* --- Finding 2: damping / shrinkage ----------------------------------------- */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h3 id="diagnostics-damping-heading" className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
            2. Shrinkage toward the baseline is degenerate
          </h3>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            Blending the choice model&rsquo;s prediction with the no-change baseline (
            <code className="rounded px-1 py-0.5 text-xs" style={{ background: "var(--surface-2)" }}>
              {diagnostics.damping.predictor}
            </code>
            ) tests whether damping the model&rsquo;s magnitude while keeping its directional signal
            can beat no-change on weighted MAE. It can&rsquo;t: the <strong>in-sample, oracle</strong>{" "}
            lambda* -- chosen with hindsight, by argmin over the exact plans being scored -- is{" "}
            <strong>{damping.oracleLambdaLabel}</strong>. The &ldquo;best&rdquo; damped predictor simply{" "}
            <em>is</em> the no-change baseline; there is no genuine magnitude improvement to be had here.
            The <strong>leave-one-plan-out cross-validated (LOPO-CV) estimate</strong> -- the honest,
            out-of-sample figure -- agrees: {damping.lopoFoldsAtOracleLambda} of {damping.lopoTotalFolds}{" "}
            folds ({damping.lopoFoldsAtOracleLambdaPct}) also choose lambda={damping.oracleLambdaLabel}, and
            its weighted MAE ({damping.lopoWeightedMaePct}) is worse than no-change&rsquo;s (
            {damping.noChangeWeightedMaePct}).
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <StatTile
            label="Oracle λ* (in-sample -- NOT a validated result)"
            value={damping.oracleLambdaLabel}
            status={damping.badge}
            caption={`Weighted MAE at λ*: ${damping.oracleWeightedMaePct}, identical to the no-change baseline (${damping.noChangeWeightedMaePct}) -- chosen with hindsight over the same plans it's scored against.`}
          />
          <StatTile
            label="LOPO-CV weighted MAE (honest, out-of-sample)"
            value={damping.lopoWeightedMaePct}
            status={{ status: "critical", label: "Worse than no-change out-of-sample" }}
            caption={`${damping.lopoFoldsAtOracleLambda} of ${damping.lopoTotalFolds} folds (${damping.lopoFoldsAtOracleLambdaPct}) independently choose λ=${damping.oracleLambdaLabel} too.`}
          />
        </div>

        <DiagnosticsLambdaSweepChart
          points={sweepPoints}
          maeDomain={maeDomain}
          lopoWeightedMae={diagnostics.damping.leave_one_plan_out_cv.weighted_mae}
          lopoWeightedMaePct={damping.lopoWeightedMaePct}
        />
      </div>

      {/* --- Finding 3: error concentration ----------------------------------------- */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h3 id="diagnostics-concentration-heading" className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
            3. The error is concentrated in one plan
          </h3>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            The published size-weighted MAE is not a diffuse error spread evenly across the market.{" "}
            {errorConcentration.topContributorSharePct} of it comes from a single plan, and{" "}
            {errorConcentration.nPlansTo80Pct} of {errorConcentration.nPlansScored} scored plans account
            for 80% of it. {errorConcentration.newEntrantCount} new-entrant plans (no 2024 enrollment)
            contribute exactly zero to this weighted metric by construction -- that&rsquo;s a blind spot
            of a size-weighted metric, not evidence the model is accurate for new entrants.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatTile
            label={`${errorConcentration.topContributor.plan_key} (${errorConcentration.topContributor.name}): share of total weighted MAE`}
            value={errorConcentration.topContributorSharePct}
            status={errorConcentration.badge}
            caption={`${errorConcentration.topContributor.org}, ${formatCount(errorConcentration.topContributor.enrollment_2024)} 2024 enrollees. Predicted share ${errorConcentration.topContributorPrior2024Pct} → ${errorConcentration.topContributorPredictedPct}; actual stayed flat at ${errorConcentration.topContributorActualPct}.`}
          />
          <StatTile
            label="Plans needed to reach 80% of total error"
            value={`${errorConcentration.nPlansTo80Pct} of ${errorConcentration.nPlansScored}`}
            status={errorConcentration.badge}
            caption={`${errorConcentration.nPlansTo50Pct} plan${errorConcentration.nPlansTo50Pct === 1 ? "" : "s"} alone reach 50% of total weighted MAE.`}
          />
          <StatTile
            label="New-entrant plans (zero weight by construction)"
            value={`${errorConcentration.newEntrantCount}`}
            status={{ status: "muted", label: "Blind spot, not accuracy" }}
            caption={errorConcentration.newEntrantNote}
          />
        </div>

        <TopContributorsTable rows={topContributors} highlightPlanKey={errorConcentration.topContributor.plan_key} />
      </div>
    </section>
  );
}

function TopContributorsTable({
  rows,
  highlightPlanKey,
}: {
  rows: DiagnosticsFile["error_decomposition"]["top_contributors"];
  highlightPlanKey: string;
}) {
  return (
    <div className="scroll-container rounded-xl border" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <caption className="sr-only">
          Plans ranked by contribution to the total size-weighted MAE, with a running cumulative share of total
          error.
        </caption>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            <th className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
              Plan
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              2024 enrollment
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              2024 share
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              2025 predicted
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              2025 actual
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              Cumulative share of total error
            </th>
          </tr>
        </thead>
        <tbody style={{ fontVariantNumeric: "tabular-nums" }}>
          {rows.map((row) => {
            const isTop = row.plan_key === highlightPlanKey;
            return (
              <tr
                key={row.plan_key}
                style={{
                  borderBottom: "1px solid var(--gridline)",
                  background: isTop ? "var(--surface-2)" : "transparent",
                }}
              >
                <td className="px-3 py-2" style={{ color: "var(--text-primary)", fontWeight: isTop ? 600 : 400 }}>
                  {row.name}
                  <span className="ml-1 text-xs" style={{ color: "var(--text-muted)" }}>
                    ({row.org})
                  </span>
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>
                  {formatCount(row.enrollment_2024)}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                  {formatPercent(row.share_2024)}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                  {formatPercent(row.share_2025_pred_logit)}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                  {formatPercent(row.share_2025_actual)}
                </td>
                <td
                  className="px-3 py-2 text-right"
                  style={{ color: isTop ? "var(--status-critical)" : "var(--text-primary)", fontWeight: isTop ? 600 : 400 }}
                >
                  {formatPercent(row.cumulative_share_of_total)}
                  {isTop && (
                    <span className="ml-1" title={`Abs. error ${formatAbsPP(row.abs_error)}`}>
                      ★
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
