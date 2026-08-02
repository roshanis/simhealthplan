// @vitest-environment jsdom
/**
 * `MiniBarCompare`'s whole job is "one row is the point (accent hue), the
 * rest are context (muted gray)" -- these tests check the actual rendered
 * bar widths/colors for that split, plus the `maxValue === 0` degenerate
 * case the width formula has to guard against (a division by zero would
 * otherwise produce `NaN%`).
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { MiniBarCompare } from "@/components/ui/MiniBarCompare";
import type { MiniBarRow } from "@/components/ui/MiniBarCompare";

describe("MiniBarCompare", () => {
  it("renders one row per input, with its label and formatted value", () => {
    const rows: MiniBarRow[] = [
      { key: "model", label: "This model", value: 0.0123, valueLabel: "1.23pp", emphasize: true },
      { key: "no_change", label: "No-change baseline", value: 0.0042, valueLabel: "0.42pp" },
    ];
    render(<MiniBarCompare rows={rows} maxValue={0.0123} />);
    expect(screen.getByText("This model")).toBeInTheDocument();
    expect(screen.getByText("1.23pp")).toBeInTheDocument();
    expect(screen.getByText("No-change baseline")).toBeInTheDocument();
    expect(screen.getByText("0.42pp")).toBeInTheDocument();
  });

  it("colors only the emphasized row with the accent series hue -- the rest stay muted gray", () => {
    const rows: MiniBarRow[] = [
      { key: "model", label: "This model", value: 10, valueLabel: "10", emphasize: true },
      { key: "trend", label: "Trend baseline", value: 5, valueLabel: "5" },
    ];
    render(<MiniBarCompare rows={rows} maxValue={10} />);
    expect(screen.getByText("10").closest("span")).toHaveStyle({ color: "var(--series-1)" });
    expect(screen.getByText("5").closest("span")).toHaveStyle({ color: "var(--text-secondary)" });
  });

  it("scales bar width proportionally to maxValue, with a 2% floor so a near-zero row is still visible", () => {
    const rows: MiniBarRow[] = [
      { key: "half", label: "Half", value: 5, valueLabel: "5" },
      { key: "tiny", label: "Tiny", value: 0.001, valueLabel: "0" },
    ];
    render(<MiniBarCompare rows={rows} maxValue={10} />);
    const halfBar = screen.getByText("Half").parentElement!.querySelector(":scope > div > div") as HTMLElement;
    expect(halfBar).toHaveStyle({ width: "50%" });
    const tinyBar = screen.getByText("Tiny").parentElement!.querySelector(":scope > div > div") as HTMLElement;
    expect(tinyBar).toHaveStyle({ width: "2%" }); // floored, not 0.01%
  });

  it("degrades gracefully to 0-width bars when maxValue is 0, instead of dividing by zero into NaN%", () => {
    const rows: MiniBarRow[] = [{ key: "a", label: "A", value: 0, valueLabel: "0" }];
    render(<MiniBarCompare rows={rows} maxValue={0} />);
    const bar = screen.getByText("A").parentElement!.querySelector(":scope > div > div") as HTMLElement;
    expect(bar.style.width).toBe("0%");
    expect(bar.style.width).not.toContain("NaN");
  });

  it("renders nothing (no rows) without crashing when given an empty row list", () => {
    render(<MiniBarCompare rows={[]} maxValue={10} />);
    // No assertion beyond "didn't throw" -- there is nothing to query for.
  });
});
