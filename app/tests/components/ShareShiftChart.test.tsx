// @vitest-environment jsdom
/**
 * `ShareShiftChart` renders as a hand-rolled SVG dot plot by default, with a
 * `<table>` twin behind a "View as table" toggle -- the WCAG-clean
 * equivalent the file-level docstring calls out (screen readers get real
 * `<td>` cells with plain text values instead of having to parse an SVG's
 * `aria-label` soup). That table view is this suite's main focus: it's the
 * one accessible path a user with a screen reader or without a pointer
 * actually depends on, so a regression there is a real a11y regression, not
 * a cosmetic one.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { ShareShiftChart } from "@/components/report/ShareShiftChart";
import { backtest } from "@/lib/data/loaders";
import { bestNaiveVariant, buildShareShiftRows, OTHER_ROW_KEY } from "@/lib/report/shareShift";
import type { ShareShiftRow } from "@/lib/report/shareShift";

// Real, committed backtest.json -- 94 real plan rows, well past the default
// topN=15, so this always exercises the "All other plans" aggregate row too.
const REAL_BEST_NAIVE = bestNaiveVariant(backtest.summary);
const REAL_ROWS = buildShareShiftRows(backtest.per_plan, REAL_BEST_NAIVE);

/** Two hand-built rows with known, easy-to-eyeball pp values -- lets the
 * table-view assertions check exact cell text rather than merely "some
 * number is present somewhere," which the real 94-row dataset makes
 * impractical to do precisely. */
function makeRows(): ShareShiftRow[] {
  return [
    {
      key: "H0001-001",
      label: "Acme Gold Plan",
      org: "Acme",
      enrollment2024: 12345,
      predictedPP: 1.23,
      actualPP: -0.45,
      bestNaivePP: 0.1,
      isAggregate: false,
    },
    {
      key: OTHER_ROW_KEY,
      label: "All other plans",
      org: null,
      enrollment2024: 999,
      predictedPP: 0.02,
      actualPP: 0.03,
      bestNaivePP: 0,
      isAggregate: true,
      aggregatedCount: 5,
    },
  ];
}

describe("ShareShiftChart -- chart view (default)", () => {
  it("renders the SVG dot plot with a descriptive aria-label sized to the row count, using real backtest.json data", () => {
    render(<ShareShiftChart rows={REAL_ROWS} bestNaive={REAL_BEST_NAIVE} />);
    expect(
      screen.getByLabelText(
        `2024 to 2025 predicted vs actual plan share shift, in percentage points, for the top ${REAL_ROWS.length} plans by 2024 enrollment`,
      ),
    ).toBeInTheDocument();
    // No table in chart view.
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("gives every row its own accessible group label (not flattened away by role=img)", () => {
    render(<ShareShiftChart rows={makeRows()} bestNaive="no_change" />);
    expect(
      screen.getByRole("group", { name: "Acme Gold Plan: predicted +1.23pp, actual -0.45pp, no-change baseline +0.10pp" }),
    ).toBeInTheDocument();
  });
});

describe("ShareShiftChart -- table view fallback", () => {
  it("toggles to a real <table> with a plain-text row per plan on click, and back again", () => {
    render(<ShareShiftChart rows={makeRows()} bestNaive="no_change" />);

    const toggle = screen.getByRole("button", { name: "View as table" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);

    // Chart is gone; table is present.
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "View as chart" })).toBeInTheDocument();

    // Column headers, including the dynamic naive-baseline label.
    expect(within(table).getByText("Plan")).toBeInTheDocument();
    expect(within(table).getByText("2024 enrollment")).toBeInTheDocument();
    expect(within(table).getByText("Predicted")).toBeInTheDocument();
    expect(within(table).getByText("Actual")).toBeInTheDocument();
    expect(within(table).getByText("no-change baseline")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View as table" })).toBeInTheDocument();
  });

  it("renders exact formatted values per row -- enrollment via formatCount, pp via formatSignedPP", () => {
    render(<ShareShiftChart rows={makeRows()} bestNaive="no_change" />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));

    const row = screen.getByText("Acme Gold Plan").closest("tr")!;
    expect(within(row).getByText("12,345")).toBeInTheDocument();
    expect(within(row).getByText("+1.23pp")).toBeInTheDocument();
    expect(within(row).getByText("-0.45pp")).toBeInTheDocument();
    expect(within(row).getByText("+0.10pp")).toBeInTheDocument();
  });

  it("shows the trend-baseline column label when trend is the selected best-naive variant", () => {
    render(<ShareShiftChart rows={makeRows()} bestNaive="trend" />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    expect(screen.getByText("trend baseline")).toBeInTheDocument();
    expect(screen.queryByText("no-change baseline")).not.toBeInTheDocument();
  });

  it("includes the aggregated 'All other plans' row in the table, same as the chart", () => {
    render(<ShareShiftChart rows={makeRows()} bestNaive="no_change" />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const row = screen.getByText("All other plans").closest("tr")!;
    expect(within(row).getByText("999")).toBeInTheDocument();
    expect(within(row).getByText("+0.02pp")).toBeInTheDocument();
  });

  it("table view survives real (large) backtest.json data without crashing and lists every row", () => {
    render(<ShareShiftChart rows={REAL_ROWS} bestNaive={REAL_BEST_NAIVE} />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(REAL_ROWS.length + 1); // +1 header row
    expect(within(table).getByText("All other plans")).toBeInTheDocument();
  });
});
