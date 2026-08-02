"use client";

/**
 * The lambda sweep for `share_damped(lambda) = lambda*logit + (1-lambda)*no_change`
 * (Finding 2, "shrinkage toward the baseline is degenerate"). A single muted line --
 * deliberately NOT the report's accent blue, since the point of this chart is that
 * damping never earns its way to a genuine improvement -- with the in-sample oracle
 * point (lambda=0) called out in the critical-status hue, and a dashed reference line
 * for the leave-one-plan-out cross-validated (honest, out-of-sample) weighted MAE.
 *
 * Accessibility follows `ShareShiftChart`'s pattern exactly: the SVG is not the only
 * path to the data. A "View as table" toggle swaps in a real `<table>` listing every
 * swept lambda's weighted MAE and directional accuracy as plain text, plus the LOPO-CV
 * estimate as its own explicitly-labelled row -- the WCAG-clean equivalent for anyone
 * who can't (or doesn't want to) parse an SVG line chart.
 */

import { useState } from "react";

import type { LambdaSweepPoint } from "@/lib/report/diagnosticsFacts";

const CHART_WIDTH = 640;
const PLOT_HEIGHT = 200;
const PADDING_TOP = 28;
const PADDING_BOTTOM = 36;
const PADDING_LEFT = 56;
const PADDING_RIGHT = 24;
const PLOT_WIDTH = CHART_WIDTH - PADDING_LEFT - PADDING_RIGHT;
const CHART_HEIGHT = PLOT_HEIGHT + PADDING_TOP + PADDING_BOTTOM;

export function DiagnosticsLambdaSweepChart({
  points,
  maeDomain,
  lopoWeightedMae,
  lopoWeightedMaePct,
}: {
  points: LambdaSweepPoint[];
  maeDomain: number;
  lopoWeightedMae: number;
  lopoWeightedMaePct: string;
}) {
  const [tableView, setTableView] = useState(false);
  const [hovered, setHovered] = useState<number | null>(null);

  const xScale = (lambda: number) => PADDING_LEFT + lambda * PLOT_WIDTH;
  const yScale = (mae: number) => PADDING_TOP + (1 - mae / maeDomain) * PLOT_HEIGHT;

  const xTicks = [0, 0.25, 0.5, 0.75, 1];
  const yTicks = [0, maeDomain / 2, maeDomain];

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${xScale(p.lambda)},${yScale(p.weightedMae)}`).join(" ");
  const oraclePoint = points.find((p) => p.isOracle);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ul className="flex flex-wrap items-center gap-4 text-xs" style={{ color: "var(--text-secondary)" }}>
          <li className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-3" style={{ background: "var(--text-muted)" }} />
            Damped predictor, weighted MAE by λ
          </li>
          <li className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--status-critical)" }} />
            Oracle λ* (in-sample)
          </li>
          <li className="flex items-center gap-1.5">
            <span
              className="inline-block h-0.5 w-3"
              style={{ background: "var(--status-critical)", opacity: 0.6, borderTop: "1px dashed var(--status-critical)" }}
            />
            LOPO-CV weighted MAE (honest, out-of-sample)
          </li>
        </ul>
        <button
          type="button"
          onClick={() => setTableView((v) => !v)}
          className="rounded-md border px-3 py-1.5 text-xs font-medium"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          aria-pressed={tableView}
        >
          {tableView ? "View as chart" : "View as table"}
        </button>
      </div>

      {tableView ? (
        <LambdaSweepTable points={points} lopoWeightedMaePct={lopoWeightedMaePct} />
      ) : (
        <div className="scroll-container rounded-xl border" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <svg
            aria-label={`Weighted MAE across ${points.length} damping lambda values from 0 (no-change baseline) to 1 (pure choice model), with the in-sample oracle optimum and the leave-one-plan-out cross-validated honest estimate both marked`}
            width={CHART_WIDTH}
            height={CHART_HEIGHT}
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            className="min-w-full"
          >
            {yTicks.map((tick) => (
              <line
                key={`grid-${tick}`}
                x1={PADDING_LEFT}
                x2={CHART_WIDTH - PADDING_RIGHT}
                y1={yScale(tick)}
                y2={yScale(tick)}
                stroke="var(--gridline)"
                strokeWidth={1}
              />
            ))}
            {yTicks.map((tick) => (
              <text
                key={`ylabel-${tick}`}
                x={PADDING_LEFT - 8}
                y={yScale(tick)}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={11}
                fill="var(--text-muted)"
              >
                {(tick * 100).toFixed(1)}pp
              </text>
            ))}
            {xTicks.map((tick) => (
              <text
                key={`xlabel-${tick}`}
                x={xScale(tick)}
                y={CHART_HEIGHT - PADDING_BOTTOM + 18}
                textAnchor="middle"
                fontSize={11}
                fill="var(--text-muted)"
              >
                {tick.toFixed(2)}
              </text>
            ))}
            <text
              x={PADDING_LEFT + PLOT_WIDTH / 2}
              y={CHART_HEIGHT - 6}
              textAnchor="middle"
              fontSize={11}
              fill="var(--text-muted)"
            >
              λ (0 = no-change baseline, 1 = pure choice model)
            </text>

            {/* LOPO-CV honest out-of-sample reference line -- dashed, critical hue,
                deliberately the same status color as the oracle point: both mark the
                same underlying finding (damping can't beat no_change) from two angles. */}
            <line
              x1={PADDING_LEFT}
              x2={CHART_WIDTH - PADDING_RIGHT}
              y1={yScale(lopoWeightedMae)}
              y2={yScale(lopoWeightedMae)}
              stroke="var(--status-critical)"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              opacity={0.7}
            />
            <text
              x={CHART_WIDTH - PADDING_RIGHT}
              y={yScale(lopoWeightedMae) - 6}
              textAnchor="end"
              fontSize={10}
              fill="var(--status-critical)"
            >
              LOPO-CV (honest): {lopoWeightedMaePct}
            </text>

            <path d={linePath} fill="none" stroke="var(--text-muted)" strokeWidth={2} />

            {points.map((p, i) => {
              const isHovered = hovered === i;
              const cx = xScale(p.lambda);
              const cy = yScale(p.weightedMae);
              return (
                <g
                  key={p.lambdaLabel}
                  onMouseEnter={() => setHovered(i)}
                  onMouseLeave={() => setHovered((h) => (h === i ? null : h))}
                  onFocus={() => setHovered(i)}
                  onBlur={() => setHovered((h) => (h === i ? null : h))}
                  tabIndex={0}
                  role="group"
                  aria-label={`lambda ${p.lambdaLabel}${p.isOracle ? " (oracle, in-sample optimum)" : ""}: weighted MAE ${p.weightedMaePct}, directional accuracy ${p.directionalAccuracyPct}`}
                  style={{ cursor: "pointer", outline: "none" }}
                >
                  <rect x={cx - 12} y={PADDING_TOP - 8} width={24} height={PLOT_HEIGHT + 16} fill={isHovered ? "var(--surface-2)" : "transparent"} />
                  <circle
                    cx={cx}
                    cy={cy}
                    r={p.isOracle ? 6 : 3.5}
                    fill={p.isOracle ? "var(--status-critical)" : "var(--text-muted)"}
                    stroke="var(--surface-1)"
                    strokeWidth={2}
                  />
                  {p.isOracle && (
                    <text x={cx} y={cy - 12} textAnchor="middle" fontSize={10} fontWeight={600} fill="var(--status-critical)">
                      oracle λ*
                    </text>
                  )}
                </g>
              );
            })}
          </svg>

          {hovered !== null && (
            <div
              className="mx-3 mb-3 flex flex-wrap gap-x-6 gap-y-1 rounded-lg border px-3 py-2 text-xs"
              style={{ borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--text-secondary)" }}
              role="status"
            >
              <span className="font-semibold" style={{ color: "var(--text-primary)" }}>
                λ = {points[hovered].lambdaLabel}
                {points[hovered].isOracle ? " (oracle, in-sample)" : ""}
              </span>
              <span>
                Weighted MAE: <strong style={{ color: "var(--text-primary)" }}>{points[hovered].weightedMaePct}</strong>
              </span>
              <span>
                Directional accuracy:{" "}
                <strong style={{ color: "var(--text-primary)" }}>{points[hovered].directionalAccuracyPct}</strong>
              </span>
            </div>
          )}
        </div>
      )}

      {!tableView && oraclePoint && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          The dashed line is the leave-one-plan-out cross-validated (LOPO-CV) weighted MAE -- the honest,
          out-of-sample estimate. It sits above every point on the sweep, including the in-sample oracle optimum
          itself, because the oracle number is fit to the very data it&rsquo;s scored against.
        </p>
      )}
    </div>
  );
}

function LambdaSweepTable({
  points,
  lopoWeightedMaePct,
}: {
  points: LambdaSweepPoint[];
  lopoWeightedMaePct: string;
}) {
  return (
    <div className="scroll-container rounded-xl border" style={{ borderColor: "var(--border)" }}>
      <table className="w-full min-w-[480px] border-collapse text-sm">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            <th className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
              λ
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              Weighted MAE
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              Directional accuracy
            </th>
            <th className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
              Note
            </th>
          </tr>
        </thead>
        <tbody style={{ fontVariantNumeric: "tabular-nums" }}>
          {points.map((p) => (
            <tr key={p.lambdaLabel} style={{ borderBottom: "1px solid var(--gridline)" }}>
              <td className="px-3 py-2" style={{ color: "var(--text-primary)", fontWeight: p.isOracle ? 600 : 400 }}>
                {p.lambdaLabel}
              </td>
              <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                {p.weightedMaePct}
              </td>
              <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                {p.directionalAccuracyPct}
              </td>
              <td className="px-3 py-2" style={{ color: "var(--status-critical)" }}>
                {p.isOracle ? "Oracle λ* -- in-sample optimum, not validated" : ""}
              </td>
            </tr>
          ))}
          <tr>
            <td className="px-3 py-2 font-semibold" style={{ color: "var(--text-primary)" }}>
              LOPO-CV
            </td>
            <td className="px-3 py-2 text-right font-semibold" style={{ color: "var(--text-primary)" }}>
              {lopoWeightedMaePct}
            </td>
            <td className="px-3 py-2 text-right" style={{ color: "var(--text-muted)" }}>
              --
            </td>
            <td className="px-3 py-2" style={{ color: "var(--status-critical)" }}>
              Honest, out-of-sample estimate (not a single λ on the sweep above)
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
