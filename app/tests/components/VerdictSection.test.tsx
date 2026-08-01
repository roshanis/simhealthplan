// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

// Vitest runs without globals, so testing-library's auto-cleanup never
// registers; without this the DOM accumulates across tests in this file.
afterEach(cleanup);

import { VerdictSection } from "@/components/report/VerdictSection";
import type { BacktestSummary } from "@/lib/data/types";

function makeSummary(overrides: Partial<BacktestSummary> = {}): BacktestSummary {
  return {
    best_naive: { selected: "no_change", weighted_mae: { no_change: 0.0041865, trend: 0.006 } },
    beats_naive: { logit: false, blended: null },
    directional_accuracy: { logit: 0.714, blended: null, no_change: 0.5, trend: 0.55 },
    outside_share_error: { logit: 0.01, blended: null, no_change: 0.02, trend: 0.02 },
    weighted_mae: { logit: 0.0123479, blended: null, no_change: 0.0041865, trend: 0.006 },
    ...overrides,
  };
}

describe("VerdictSection", () => {
  it("labels the MAE tile 'Worse than baseline' when beats_naive.logit is false (the pilot's actual frozen result)", () => {
    render(<VerdictSection summary={makeSummary()} />);
    expect(screen.getByText("Worse than baseline")).toBeInTheDocument();
  });

  it("labels the MAE tile 'Better than baseline' when beats_naive.logit is true", () => {
    render(<VerdictSection summary={makeSummary({ beats_naive: { logit: true, blended: null } })} />);
    expect(screen.getByText("Better than baseline")).toBeInTheDocument();
  });

  it("labels the MAE tile 'Pending' when beats_naive.logit is null", () => {
    render(<VerdictSection summary={makeSummary({ beats_naive: { logit: null, blended: null } })} />);
    expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
  });

  it("labels the accuracy tile 'Better than both baselines' when the model's directional accuracy beats both naive baselines", () => {
    render(
      <VerdictSection
        summary={makeSummary({ directional_accuracy: { logit: 0.714, blended: null, no_change: 0.5, trend: 0.55 } })}
      />,
    );
    // Appears in more than one tile by design (e.g. a summary line), so
    // assert presence rather than uniqueness.
    expect(screen.getAllByText("Better than both baselines").length).toBeGreaterThan(0);
  });

  it("labels the accuracy tile 'Better than one baseline' when the model beats only one naive baseline", () => {
    render(
      <VerdictSection
        summary={makeSummary({ directional_accuracy: { logit: 0.52, blended: null, no_change: 0.5, trend: 0.6 } })}
      />,
    );
    expect(screen.getByText("Better than one baseline")).toBeInTheDocument();
  });

  it("labels the accuracy tile 'Worse than both baselines' when the model beats neither naive baseline", () => {
    render(
      <VerdictSection
        summary={makeSummary({ directional_accuracy: { logit: 0.4, blended: null, no_change: 0.5, trend: 0.6 } })}
      />,
    );
    expect(screen.getByText("Worse than both baselines")).toBeInTheDocument();
  });

  it("shows the blended tile as 'Not yet run' when weighted_mae.blended is null", () => {
    render(<VerdictSection summary={makeSummary()} />);
    expect(screen.getByText("Not yet run")).toBeInTheDocument();
    expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
  });

  it("derives the blended tile's badge from beats_naive.blended once blended results exist", () => {
    render(
      <VerdictSection
        summary={makeSummary({
          beats_naive: { logit: false, blended: false },
          directional_accuracy: { logit: 0.714, blended: 0.692, no_change: 0.5, trend: 0.55 },
          weighted_mae: { logit: 0.0123479, blended: 0.0141363, no_change: 0.0041865, trend: 0.006 },
        })}
      />,
    );
    expect(screen.queryByText("Not yet run")).not.toBeInTheDocument();
    // Both the base-model MAE tile and the blended tile trail the baseline here.
    expect(screen.getAllByText("Worse than baseline").length).toBe(2);
  });

  it("states the mixed result plainly, without hiding beats_naive.logit === false", () => {
    render(<VerdictSection summary={makeSummary()} />);
    expect(screen.getAllByText(/assuming nothing changes was more accurate/i).length).toBeGreaterThan(0);
  });
});
