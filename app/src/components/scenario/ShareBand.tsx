/**
 * Compact "same-hue lighter ribbon" band: p10-p90 Monte Carlo range in a
 * light tint of the accent hue, with solid ticks marking the baseline
 * (muted gray) and scenario (accent) point estimates. One shared linear
 * domain per row (padded min/max across baseline/scenario/bounds) so the
 * ribbon width is honestly comparable row to row within one table.
 */

function pct(value: number, min: number, max: number): number {
  if (max <= min) return 50;
  return ((value - min) / (max - min)) * 100;
}

export function ShareBand({
  baseline,
  scenario,
  p10,
  p90,
}: {
  baseline: number;
  scenario: number;
  p10: number;
  p90: number;
}) {
  const rawMin = Math.min(baseline, scenario, p10, p90);
  const rawMax = Math.max(baseline, scenario, p10, p90);
  const pad = Math.max((rawMax - rawMin) * 0.15, 0.0005);
  const min = Math.max(0, rawMin - pad);
  const max = rawMax + pad;

  const asPct = (v: number) => `${(v * 100).toFixed(2)}%`;

  return (
    <div className="relative h-5 w-full min-w-[120px]" style={{ background: "var(--surface-2)", borderRadius: 4 }}>
      <span className="sr-only">
        {`Scenario share ${asPct(scenario)} (baseline ${asPct(baseline)}); 80% interval ${asPct(p10)} to ${asPct(p90)} (p10 to p90).`}
      </span>
      <div
        className="absolute top-0 h-full"
        style={{
          left: `${pct(p10, min, max)}%`,
          width: `${Math.max(pct(p90, min, max) - pct(p10, min, max), 1)}%`,
          background: "var(--series-1)",
          opacity: 0.22,
          borderRadius: 4,
        }}
        aria-hidden="true"
      />
      <div
        className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2"
        style={{ left: `${pct(baseline, min, max)}%`, background: "var(--text-muted)" }}
        aria-hidden="true"
      />
      <div
        className="absolute top-1/2 h-4 w-1 -translate-y-1/2 rounded-full"
        style={{ left: `${pct(scenario, min, max)}%`, background: "var(--series-1)" }}
        aria-hidden="true"
      />
    </div>
  );
}
