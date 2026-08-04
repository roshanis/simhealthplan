// @vitest-environment jsdom
/**
 * `ScenarioDemo` covers two things called out as easy to silently break:
 *
 *  1. Plan-label rendering in the "2025 plan" dropdown -- `planLabel()`
 *     must not duplicate the org name for the ~41% of real plans whose
 *     `plan_name` already leads with it (e.g. Humana). This is exercised
 *     against the real, committed `scenario_inputs.json` roster, not a
 *     hand-built fixture, so a future data refresh that reintroduces a
 *     duplicated label would actually be caught here.
 *  2. The preset buttons populate the *same* state the manual controls do
 *     (`selectPlan` + explicit overrides) -- clicking one must visibly move
 *     the plan dropdown / premium slider readout / benefit checkboxes, not
 *     just silently set some parallel piece of state nothing renders.
 *
 * No network call is made anywhere in this file: none of these tests click
 * "Run scenario", so `fetch("/api/scenario")` is never reached (that round
 * trip is already covered end-to-end in `tests/api/scenario.test.ts`).
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ScenarioDemo } from "@/components/scenario/ScenarioDemo";
import { scenarioInputs } from "@/lib/data/loaders";

// Real, committed roster (94 plans). The largest by enrollment is
// H0321-002 (UHC Dual Complete AZ-S001) -- see the component's own
// docstring, which names it as the same plan the first preset targets.
const REAL_PLANS = scenarioInputs.plans;
const EMPTY_BASELINES: Record<string, number> = {};

describe("ScenarioDemo -- plan-label rendering", () => {
  it("renders a Humana plan whose plan_name already leads with the org name WITHOUT duplicating it", () => {
    render(<ScenarioDemo plans={REAL_PLANS} baselineShares={EMPTY_BASELINES} />);
    const option = screen.getByRole("option", { name: /Humana Gold Plus H0028-023 \(HMO\)/ });
    expect(option.textContent).toContain("Humana Gold Plus H0028-023 (HMO)");
    expect(option.textContent).not.toMatch(/Humana\s+Humana/i);
  });

  it("falls back to 'org + plan name' concatenation for a plan whose name does NOT lead with the org", () => {
    render(<ScenarioDemo plans={REAL_PLANS} baselineShares={EMPTY_BASELINES} />);
    // AZ Blue's plan_name ("Blue Best Life Classic (HMO)") does not start
    // with its org_name ("Blue Cross Blue Shield of Arizona (AZ Blue)").
    const option = screen.getByRole("option", {
      name: /Blue Cross Blue Shield of Arizona \(AZ Blue\) Blue Best Life Classic \(HMO\)/,
    });
    expect(option).toBeInTheDocument();
  });
});

describe("ScenarioDemo -- preset buttons populate the form through the normal state path", () => {
  it("'Raise premium $20' selects Humana Gold Plus H0028-074 in the dropdown and sets the premium readout", () => {
    render(<ScenarioDemo plans={REAL_PLANS} baselineShares={EMPTY_BASELINES} />);

    const select = screen.getByLabelText("2025 plan") as HTMLSelectElement;
    // Not already selected -- the default is the largest plan (H0321-002),
    // so this assertion actually exercises selectPlan() moving it.
    expect(select.value).not.toBe("H0028-074");

    fireEvent.click(screen.getByRole("button", { name: /Raise premium \$20/ }));

    expect(select.value).toBe("H0028-074");
    // `formatMoneyDelta(delta, 0)` -- zero decimal digits for the slider
    // readout, so "+$20/mo" (not "+$20.00/mo").
    expect(screen.getByText("+$20/mo")).toBeInTheDocument();
    // "Run scenario" gates on changes.length > 0 -- a real behavioural
    // consequence of the preset having actually populated state, not just
    // a label change.
    expect(screen.getByRole("button", { name: "Run scenario" })).toBeEnabled();
  });

  it("'Cut premium $15, drop dental' sets the premium readout and unchecks the dental toggle", () => {
    render(<ScenarioDemo plans={REAL_PLANS} baselineShares={EMPTY_BASELINES} />);

    fireEvent.click(screen.getByRole("button", { name: /Cut premium \$15, drop dental/ }));

    expect(screen.getByText("-$15/mo")).toBeInTheDocument();
    expect(screen.getByLabelText("Comprehensive dental")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Run scenario" })).toBeEnabled();
  });

  it("'Add comprehensive dental' selects the AZ Blue plan and checks the dental toggle it currently lacks", () => {
    render(<ScenarioDemo plans={REAL_PLANS} baselineShares={EMPTY_BASELINES} />);

    const select = screen.getByLabelText("2025 plan") as HTMLSelectElement;
    fireEvent.click(screen.getByRole("button", { name: /Add comprehensive dental/ }));

    expect(select.value).toBe("H0302-006");
    expect(screen.getByLabelText("Comprehensive dental")).toBeChecked();
  });

  it("picking a plan manually from the dropdown still works (the preset path is additive, not a replacement)", () => {
    render(<ScenarioDemo plans={REAL_PLANS} baselineShares={EMPTY_BASELINES} />);
    const select = screen.getByLabelText("2025 plan") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "H0028-023" } });
    expect(select.value).toBe("H0028-023");
    // No changes yet (selecting alone doesn't move a slider/checkbox away
    // from that plan's own baseline) -- run stays disabled.
    expect(screen.getByRole("button", { name: "Run scenario" })).toBeDisabled();
  });

  it("shows the baseline-share placeholder (not a results table) until a scenario is actually run", () => {
    render(<ScenarioDemo plans={REAL_PLANS} baselineShares={EMPTY_BASELINES} />);
    expect(screen.getByText(/Adjust the controls and run a scenario to see the effect\./)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
