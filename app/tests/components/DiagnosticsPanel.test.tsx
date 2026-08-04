// @vitest-environment jsdom
/**
 * `DiagnosticsPanel` renders the pipeline's post-hoc evaluation diagnostics
 * against the REAL, committed `diagnostics.json` -- not a hand-built fixture
 * -- so these assertions pin the pilot's actual frozen findings (17 of 94
 * plans inside the nominal 80% interval, an oracle lambda* of 0.00 vs the
 * honest LOPO-CV estimate, H0321-002 at 57.1% of total weighted error).
 * A future diagnostics rerun that silently softens, buries, or drops the
 * in-sample/out-of-sample labelling on any of these three findings should
 * fail this suite loudly, matching `ShareShiftChart.test.tsx`'s pattern of
 * testing against the real backtest.json rather than only synthetic rows.
 *
 * Many of the figures asserted here are deliberately rendered in more than
 * one place (a StatTile's headline value AND a mini-bar/table row using the
 * same formatted string) -- by design, per the report's existing "state the
 * number, then show it in context" convention (see `VerdictSection`). So
 * most assertions use `getAllByText(...).length > 0` (presence, anywhere)
 * rather than `getByText` (exactly one match), except where a string is
 * scoped with `within(...)` to a specific row/table first.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { DiagnosticsPanel } from "@/components/report/DiagnosticsPanel";
import { diagnostics } from "@/lib/data/loaders";

describe("DiagnosticsPanel -- Finding 1: confidence-band coverage is overconfident", () => {
  it("renders the real plan-level coverage (17 of 94) against the nominal 80% interval", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    expect(screen.getAllByText("18.1%").length).toBeGreaterThan(0); // unweighted coverage
    expect(screen.getAllByText(/17 of 94/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/nominal 80%/).length).toBeGreaterThan(0);
  });

  it("renders the enrollment-weighted coverage figure (43.2%), distinct from the unweighted one", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    expect(screen.getAllByText("43.2%").length).toBeGreaterThan(0);
  });

  it("renders the asymmetric miss direction (53 above vs 24 below) and calls the interval overconfident", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    expect(screen.getAllByText("53 above / 24 below").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/overconfident/i).length).toBeGreaterThan(0);
  });
});

describe("DiagnosticsPanel -- Finding 2: shrinkage toward the baseline is degenerate", () => {
  it("labels the oracle lambda* explicitly as in-sample, and the LOPO-CV figure as the honest out-of-sample estimate", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    // The oracle StatTile's own label must say "in-sample" -- never presented bare.
    // (Matches both the StatTile label and the lambda-sweep chart's legend, which
    // both independently call out the same in-sample framing -- by design.)
    expect(screen.getAllByText(/Oracle λ\* \(in-sample/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/in-sample/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/out-of-sample/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/LOPO-CV/).length).toBeGreaterThan(0);
  });

  it("renders the degenerate oracle lambda* (0.00) with a weighted MAE identical to the no-change baseline", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    expect(screen.getAllByText("0.00").length).toBeGreaterThan(0); // oracle lambda*
    expect(screen.getAllByText(/0\.42pp/).length).toBeGreaterThan(0); // oracle == no-change weighted MAE
  });

  it("renders the honest LOPO-CV weighted MAE (0.52pp, worse than no-change) as its own StatTile", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    expect(screen.getAllByText("0.52pp").length).toBeGreaterThan(0);
  });

  it("states plainly that there is no genuine improvement -- damping only wins by collapsing to no-change", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    expect(screen.getAllByText(/no genuine (magnitude )?improvement/i).length).toBeGreaterThan(0);
  });

  it("never presents the oracle number unlabelled, even in the lambda sweep's table-view equivalent", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    fireEvent.click(screen.getByRole("button", { name: "View as table" }));
    const sweepTable = screen
      .getAllByRole("table")
      .find((table) => within(table).queryByText(/Oracle λ\*/) !== null);
    expect(sweepTable).toBeDefined();
    expect(within(sweepTable!).getByText(/Oracle λ\* -- in-sample optimum, not validated/)).toBeInTheDocument();
    expect(within(sweepTable!).getByText(/Honest, out-of-sample estimate/)).toBeInTheDocument();
    // The sweep grid itself covers all 21 lambda points from the committed artifact,
    // from the no-change endpoint (0.00) through the pure-logit endpoint (1.00).
    expect(within(sweepTable!).getAllByText("0.00").length).toBeGreaterThan(0);
    expect(within(sweepTable!).getAllByText("1.00").length).toBeGreaterThan(0);
  });
});

describe("DiagnosticsPanel -- Finding 3: error is concentrated in one plan", () => {
  it("attributes 57.1% of total weighted MAE to plan H0321-002", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    expect(screen.getAllByText(/H0321-002/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("57.1%").length).toBeGreaterThan(0);
  });

  it("shows the plan's predicted share roughly doubling while actual stayed flat", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    // 2024 share 5.4% -> 2025 predicted 10.7%, actual 5.1% -- all read straight off
    // the committed artifact via diagnosticsFacts.ts, not hardcoded in the panel.
    expect(screen.getAllByText(/5\.4%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/10\.7%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/5\.1%/).length).toBeGreaterThan(0);
  });

  it("shows 4 of 94 plans reach 80% of total error", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    expect(screen.getAllByText("4 of 94").length).toBeGreaterThan(0);
  });

  it("flags the 13 new-entrant plans as a zero-weight blind spot, not evidence of accuracy", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    expect(screen.getAllByText("13").length).toBeGreaterThan(0); // new-entrant StatTile value
    expect(screen.getAllByText(/blind spot/i).length).toBeGreaterThan(0);
  });

  it("highlights H0321-002's row in the top-contributors table with its cumulative share", () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} />);
    const table = screen.getAllByRole("table")[0];
    const row = within(table).getByText(/UHC Dual Complete AZ-S001/).closest("tr")!;
    expect(within(row).getAllByText("57.1%").length).toBeGreaterThan(0);
  });
});
