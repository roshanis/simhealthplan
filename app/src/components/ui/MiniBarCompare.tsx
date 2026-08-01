/**
 * Small "emphasis" bar comparison used inside the verdict stat tiles: one
 * row is the point of the story (accent hue), the rest are context (muted
 * gray) -- the dataviz skill's `choosing-a-form.md` rule for "one series is
 * the point, rest are context." Not a categorical chart (no legend needed):
 * only one row ever carries the accent color, so its label already says
 * what it is.
 */

export interface MiniBarRow {
  key: string;
  label: string;
  value: number;
  valueLabel: string;
  emphasize?: boolean;
}

export function MiniBarCompare({ rows, maxValue }: { rows: MiniBarRow[]; maxValue: number }) {
  return (
    <div className="flex flex-col gap-2">
      {rows.map((row) => {
        const pct = maxValue > 0 ? Math.max(2, (row.value / maxValue) * 100) : 0;
        return (
          <div key={row.key} className="flex items-center gap-2">
            <span
              className="w-28 shrink-0 truncate text-xs"
              style={{ color: "var(--text-secondary)" }}
              title={row.label}
            >
              {row.label}
            </span>
            <div className="h-3 flex-1 overflow-hidden rounded" style={{ background: "var(--surface-2)" }}>
              <div
                className="h-full rounded"
                style={{
                  width: `${pct}%`,
                  background: row.emphasize ? "var(--series-1)" : "var(--text-muted)",
                }}
              />
            </div>
            <span
              className="w-16 shrink-0 text-right text-xs font-medium"
              style={{
                color: row.emphasize ? "var(--series-1)" : "var(--text-secondary)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {row.valueLabel}
            </span>
          </div>
        );
      })}
    </div>
  );
}
