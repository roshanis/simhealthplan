// @vitest-environment jsdom
/**
 * `StatTile` is a small, prop-driven presentational shell used throughout
 * `VerdictSection` -- smoke-test its branches directly (status badge
 * present/absent, caption present/absent, children slot) since those are
 * the only things that vary call to call.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { StatTile } from "@/components/ui/StatTile";

describe("StatTile", () => {
  it("renders the label and value", () => {
    render(<StatTile label="Weighted MAE" value="1.23pp" />);
    expect(screen.getByText("Weighted MAE")).toBeInTheDocument();
    expect(screen.getByText("1.23pp")).toBeInTheDocument();
  });

  it("omits the status badge entirely when no status prop is given", () => {
    render(<StatTile label="Weighted MAE" value="1.23pp" />);
    expect(screen.queryByText("✓")).not.toBeInTheDocument();
    expect(screen.queryByText("✕")).not.toBeInTheDocument();
  });

  it("renders the status badge (icon + label) when a status prop is given", () => {
    render(<StatTile label="Weighted MAE" value="1.23pp" status={{ status: "critical", label: "Loses to no-change" }} />);
    expect(screen.getByText("Loses to no-change")).toBeInTheDocument();
    expect(screen.getByText("✕")).toBeInTheDocument();
  });

  it("omits the caption paragraph when none is given, and renders it when one is", () => {
    const { rerender } = render(<StatTile label="Weighted MAE" value="1.23pp" />);
    expect(screen.queryByText(/naive baseline/)).not.toBeInTheDocument();
    rerender(<StatTile label="Weighted MAE" value="1.23pp" caption="Lower is better vs. the naive baseline." />);
    expect(screen.getByText("Lower is better vs. the naive baseline.")).toBeInTheDocument();
  });

  it("renders arbitrary children (e.g. a mini comparison chart) below the value", () => {
    render(
      <StatTile label="Weighted MAE" value="1.23pp">
        <div data-testid="mini-chart-slot">chart goes here</div>
      </StatTile>,
    );
    expect(screen.getByTestId("mini-chart-slot")).toBeInTheDocument();
  });
});
