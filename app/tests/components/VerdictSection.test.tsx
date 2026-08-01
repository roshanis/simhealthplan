// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

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
  it("labels the MAE tile 'Loses to no-change' when beats_naive.logit is false (the pilot's actual frozen result)", () => {
    render(<VerdictSection summary={makeSummary()} />);
    expect(screen.getByText("Loses to no-change")).toBeInTheDocument();
  });

  it("labels the MAE tile 'Beats no-change' when beats_naive.logit is true", () => {
    render(<VerdictSection summary={makeSummary({ beats_naive: { logit: true, blended: null } })} />);
    expect(screen.getByText("Beats no-change")).toBeInTheDocument();
  });

  it("labels the MAE tile 'Pending' when beats_naive.logit is null", () => {
    render(<VerdictSection summary={makeSummary({ beats_naive: { logit: null, blended: null } })} />);
    expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
  });

  it("labels the accuracy tile 'Beats both baselines' when the model's directional accuracy beats both naive baselines", () => {
    render(
      <VerdictSection
        summary={makeSummary({ directional_accuracy: { logit: 0.714, blended: null, no_change: 0.5, trend: 0.55 } })}
      />,
    );
    // Appears in more than one tile by design (e.g. a summary line), so
    // assert presence rather than uniqueness.
    expect(screen.getAllByText("Beats both baselines").length).toBeGreaterThan(0);
  });

  it("labels the accuracy tile 'Beats one baseline' when the model beats only one naive baseline", () => {
    render(
      <VerdictSection
        summary={makeSummary({ directional_accuracy: { logit: 0.52, blended: null, no_change: 0.5, trend: 0.6 } })}
      />,
    );
    expect(screen.getByText("Beats one baseline")).toBeInTheDocument();
  });

  it("labels the accuracy tile 'Loses to both baselines' when the model beats neither naive baseline", () => {
    render(
      <VerdictSection
        summary={makeSummary({ directional_accuracy: { logit: 0.4, blended: null, no_change: 0.5, trend: 0.6 } })}
      />,
    );
    expect(screen.getByText("Loses to both baselines")).toBeInTheDocument();
  });

  it("shows the blended tile as 'Pending' when weighted_mae.blended is null (personas.json / y2_predictions.json don't exist yet)", () => {
    render(<VerdictSection summary={makeSummary()} />);
    // Both blended tiles (MAE + accuracy) legitimately show this badge.
    expect(screen.getAllByText("Pending LLM pass").length).toBeGreaterThan(0);
  });

  it("renders the negative-result prose honestly, without hiding beats_naive.logit === false", () => {
    render(<VerdictSection summary={makeSummary()} />);
    expect(screen.getAllByText(/negative result on magnitude/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/positive result on direction/i).length).toBeGreaterThan(0);
  });
});
