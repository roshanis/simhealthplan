"use client";

/**
 * Horizontal diverging dot plot: 2024→2025 share shift (pp) for the top
 * plans by 2024 enrollment + one aggregated "All other plans" row. Two
 * categorical dot series (Predicted=logit, Actual), connected by a thin
 * dumbbell-style link, plus a muted gray reference tick for the best naive
 * baseline. Hand-rolled SVG rather than Recharts -- see the file-level note
 * in `app/page.tsx` for why (short version: full row-as-hit-target hover +
 * exact mark-spec control for this specific dumbbell/reference-tick form
 * was simpler to get right by hand than to fight a general-purpose charting
 * library's grouped-series model for it).
 *
 * Dataviz-skill compliance: categorical slots 1 (blue, Predicted) and 2
 * (green, Actual) from the validated default palette; legend always present
 * for the 2 series; direct labels on the two extreme rows only (label
 * clutter avoided elsewhere -- values live in the tooltip + table view);
 * hairline solid gridlines/baseline; 2px surface ring on every dot; each
 * row is its own hover/focus hit target (taller than the 24px minimum);
 * table-view twin toggle for the WCAG-clean equivalent.
 */

import { useState } from "react";

import { formatCount, formatSignedPP } from "@/lib/format";
import type { NaiveVariant } from "@/lib/data/types";
import { shareShiftDomain, type ShareShiftRow } from "@/lib/report/shareShift";

const ROW_HEIGHT = 32;
const CHART_PADDING_TOP = 28;
const CHART_PADDING_BOTTOM = 28;
const LABEL_COL_WIDTH = 200;
const PLOT_WIDTH = 480;
const CHART_WIDTH = LABEL_COL_WIDTH + PLOT_WIDTH + 24;

function naiveLabel(variant: NaiveVariant): string {
  return variant === "no_change" ? "no-change" : "trend";
}

const ppLabel = formatSignedPP;

export function ShareShiftChart({ rows, bestNaive }: { rows: ShareShiftRow[]; bestNaive: NaiveVariant }) {
  const [tableView, setTableView] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);

  const domain = shareShiftDomain(rows);
  const plotHeight = rows.length * ROW_HEIGHT;
  const chartHeight = plotHeight + CHART_PADDING_TOP + CHART_PADDING_BOTTOM;

  const xScale = (pp: number) => LABEL_COL_WIDTH + ((pp + domain) / (2 * domain)) * PLOT_WIDTH;
  const zeroX = xScale(0);

  const tickValues = [-domain, -domain / 2, 0, domain / 2, domain].map((v) => Math.round(v * 100) / 100);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Legend bestNaive={bestNaive} />
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
        <ShareShiftTable rows={rows} bestNaive={bestNaive} />
      ) : (
        <div className="scroll-container rounded-xl border" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          {/* No role="img": rows inside are individually focusable
              (tabIndex + aria-label), and role="img" would flatten them
              away from assistive tech. */}
          <svg
            aria-label={`2024 to 2025 predicted vs actual plan share shift, in percentage points, for the top ${rows.length} plans by 2024 enrollment`}
            width={CHART_WIDTH}
            height={chartHeight}
            viewBox={`0 0 ${CHART_WIDTH} ${chartHeight}`}
            className="min-w-full"
          >
            {/* gridlines at tick values */}
            {tickValues.map((tick) => (
              <line
                key={tick}
                x1={xScale(tick)}
                x2={xScale(tick)}
                y1={CHART_PADDING_TOP - 8}
                y2={chartHeight - CHART_PADDING_BOTTOM + 4}
                stroke="var(--gridline)"
                strokeWidth={1}
              />
            ))}
            {/* zero baseline, slightly stronger */}
            <line
              x1={zeroX}
              x2={zeroX}
              y1={CHART_PADDING_TOP - 8}
              y2={chartHeight - CHART_PADDING_BOTTOM + 4}
              stroke="var(--baseline)"
              strokeWidth={1.5}
            />

            {/* axis tick labels */}
            {tickValues.map((tick) => (
              <text
                key={`label-${tick}`}
                x={xScale(tick)}
                y={CHART_PADDING_TOP - 14}
                textAnchor="middle"
                fontSize={11}
                fill="var(--text-muted)"
              >
                {tick > 0 ? `+${tick}` : tick}
              </text>
            ))}
            <text
              x={LABEL_COL_WIDTH + PLOT_WIDTH / 2}
              y={chartHeight - 6}
              textAnchor="middle"
              fontSize={11}
              fill="var(--text-muted)"
            >
              Share shift, percentage points (2024 → 2025)
            </text>

            {rows.map((row, i) => {
              const y = CHART_PADDING_TOP + i * ROW_HEIGHT + ROW_HEIGHT / 2;
              const isHovered = hovered === row.key;
              const predX = xScale(row.predictedPP);
              const actX = xScale(row.actualPP);
              const naiveX = xScale(row.bestNaivePP);

              return (
                <g
                  key={row.key}
                  onMouseEnter={() => setHovered(row.key)}
                  onMouseLeave={() => setHovered((h) => (h === row.key ? null : h))}
                  onFocus={() => setHovered(row.key)}
                  onBlur={() => setHovered((h) => (h === row.key ? null : h))}
                  tabIndex={0}
                  role="group"
                  aria-label={`${row.label}: predicted ${ppLabel(row.predictedPP)}, actual ${ppLabel(row.actualPP)}, ${naiveLabel(bestNaive)} baseline ${ppLabel(row.bestNaivePP)}`}
                  style={{ cursor: "pointer", outline: "none" }}
                >
                  {/* full-row hit target, larger than the marks themselves */}
                  <rect
                    x={0}
                    y={y - ROW_HEIGHT / 2}
                    width={CHART_WIDTH}
                    height={ROW_HEIGHT}
                    fill={isHovered ? "var(--surface-2)" : "transparent"}
                  />

                  <text
                    x={LABEL_COL_WIDTH - 12}
                    y={y}
                    textAnchor="end"
                    dominantBaseline="middle"
                    fontSize={12}
                    fontWeight={row.isAggregate ? 600 : 400}
                    fill="var(--text-primary)"
                  >
                    {truncateLabel(row.label)}
                  </text>

                  {/* dumbbell connector */}
                  <line x1={predX} x2={actX} y1={y} y2={y} stroke="var(--text-muted)" strokeWidth={1.5} opacity={0.5} />

                  {/* best-naive reference tick: muted, not a hue */}
                  <line x1={naiveX} x2={naiveX} y1={y - 7} y2={y + 7} stroke="var(--text-muted)" strokeWidth={2} opacity={0.8} />

                  {/* actual (series 2, green) */}
                  <circle cx={actX} cy={y} r={5} fill="var(--series-2)" stroke="var(--surface-1)" strokeWidth={2} />
                  {/* predicted (series 1, blue) */}
                  <circle cx={predX} cy={y} r={5} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2} />

                  {(i === 0 || isHovered) && (
                    <text x={predX} y={y - 12} textAnchor="middle" fontSize={10} fill="var(--series-1)" fontWeight={600}>
                      {ppLabel(row.predictedPP)}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>

          {hovered && (
            <RowTooltip row={rows.find((r) => r.key === hovered)!} bestNaive={bestNaive} />
          )}
        </div>
      )}
    </div>
  );
}

function truncateLabel(label: string, max = 26): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

function Legend({ bestNaive }: { bestNaive: NaiveVariant }) {
  return (
    <ul className="flex flex-wrap items-center gap-4 text-xs" style={{ color: "var(--text-secondary)" }}>
      <li className="flex items-center gap-1.5">
        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--series-1)" }} />
        Predicted (choice model)
      </li>
      <li className="flex items-center gap-1.5">
        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--series-2)" }} />
        Actual
      </li>
      <li className="flex items-center gap-1.5">
        <span className="inline-block h-0.5 w-3" style={{ background: "var(--text-muted)" }} />
        Best naive baseline ({naiveLabel(bestNaive)})
      </li>
    </ul>
  );
}

function RowTooltip({ row, bestNaive }: { row: ShareShiftRow; bestNaive: NaiveVariant }) {
  return (
    <div
      className="mx-3 mb-3 flex flex-wrap gap-x-6 gap-y-1 rounded-lg border px-3 py-2 text-xs"
      style={{ borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--text-secondary)" }}
      role="status"
    >
      <span className="font-semibold" style={{ color: "var(--text-primary)" }}>
        {row.label}
        {row.isAggregate && row.aggregatedCount ? ` (${row.aggregatedCount} plans)` : ""}
      </span>
      <span>
        2024 enrollment: <strong style={{ color: "var(--text-primary)" }}>{formatCount(row.enrollment2024)}</strong>
      </span>
      <span>
        <span aria-hidden="true" style={{ color: "var(--series-1)" }}>
          ●{" "}
        </span>
        Predicted: <strong style={{ color: "var(--text-primary)" }}>{ppLabel(row.predictedPP)}</strong>
      </span>
      <span>
        <span aria-hidden="true" style={{ color: "var(--series-2)" }}>
          ●{" "}
        </span>
        Actual: <strong style={{ color: "var(--text-primary)" }}>{ppLabel(row.actualPP)}</strong>
      </span>
      <span>
        {naiveLabel(bestNaive)} baseline: <strong style={{ color: "var(--text-primary)" }}>{ppLabel(row.bestNaivePP)}</strong>
      </span>
    </div>
  );
}

function ShareShiftTable({ rows, bestNaive }: { rows: ShareShiftRow[]; bestNaive: NaiveVariant }) {
  return (
    <div className="scroll-container rounded-xl border" style={{ borderColor: "var(--border)" }}>
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            <th className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
              Plan
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              2024 enrollment
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              <span aria-hidden="true" style={{ color: "var(--series-1)" }}>
                ●{" "}
              </span>
              Predicted
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              <span aria-hidden="true" style={{ color: "var(--series-2)" }}>
                ●{" "}
              </span>
              Actual
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              {naiveLabel(bestNaive)} baseline
            </th>
          </tr>
        </thead>
        <tbody style={{ fontVariantNumeric: "tabular-nums" }}>
          {rows.map((row) => (
            <tr key={row.key} style={{ borderBottom: "1px solid var(--gridline)" }}>
              <td className="px-3 py-2" style={{ color: "var(--text-primary)", fontWeight: row.isAggregate ? 600 : 400 }}>
                {row.label}
              </td>
              <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>
                {formatCount(row.enrollment2024)}
              </td>
              <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                {ppLabel(row.predictedPP)}
              </td>
              <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                {ppLabel(row.actualPP)}
              </td>
              <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                {ppLabel(row.bestNaivePP)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
