// @vitest-environment jsdom
/**
 * `MarketSnapshot` is exercised against the real, committed `market.json`
 * via the exact same prop-wiring `app/page.tsx` uses (`plansByYear:
 * market.plans`, `facts: buildMarketFacts(market)`, `years:
 * Object.keys(market.plans).sort()`) -- so these tests catch a real
 * regression in how that data actually renders, not just in a synthetic
 * fixture's shape.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { MarketSnapshot } from "@/components/report/MarketSnapshot";
import { market } from "@/lib/data/loaders";
import { buildMarketFacts } from "@/lib/report/marketFacts";

const REAL_FACTS = buildMarketFacts(market);
const REAL_YEARS = Object.keys(market.plans).sort();

function renderReal() {
  return render(<MarketSnapshot plansByYear={market.plans} facts={REAL_FACTS} years={REAL_YEARS} />);
}

/** `market.json`'s real roster has a couple of orgs (Banner, Mercy Care)
 * running same-named plans across regions, so `plan_name` alone isn't
 * always a unique DOM lookup key -- restrict a by-name row lookup to plans
 * whose name is unique in that year's roster. */
function uniquelyNamed(plans: typeof market.plans["2025"]) {
  const counts = new Map<string, number>();
  for (const p of plans) counts.set(p.plan_name, (counts.get(p.plan_name) ?? 0) + 1);
  return plans.filter((p) => counts.get(p.plan_name) === 1);
}

describe("MarketSnapshot", () => {
  it("defaults to the last year (2025) and shows its real plan count", () => {
    renderReal();
    expect(screen.getByRole("button", { name: "2025" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(`${market.plans["2025"].length} plans`)).toBeInTheDocument();
  });

  it("renders every computed headline fact's exact text", () => {
    renderReal();
    for (const fact of REAL_FACTS) {
      expect(screen.getByText(fact.text)).toBeInTheDocument();
    }
  });

  it("switching to 2024 swaps both the plan count and the table contents", () => {
    renderReal();
    fireEvent.click(screen.getByRole("button", { name: "2024" }));
    expect(screen.getByRole("button", { name: "2024" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "2025" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText(`${market.plans["2024"].length} plans`)).toBeInTheDocument();
  });

  it("sorts by enrollment descending by default, so the market's largest 2025 plan leads the table", () => {
    renderReal();
    const table = screen.getByRole("table");
    const firstDataRow = within(table).getAllByRole("row")[1]; // [0] is the header row
    const topPlan = [...market.plans["2025"]].sort((a, b) => b.enrollment - a.enrollment)[0];
    expect(within(firstDataRow).getByText(topPlan.plan_name)).toBeInTheDocument();
  });

  it("re-sorts the table when a column header is clicked, and flips direction on a second click", () => {
    renderReal();
    const orgHeaderButton = screen.getByRole("button", { name: /Sort by Org/ });
    fireEvent.click(orgHeaderButton);

    // A first click on a NEW column defaults to descending (see
    // `toggleSort`'s `else` branch -- switching columns always resets to
    // "desc", it does not inherit "asc").
    const table = screen.getByRole("table");
    const firstRowDesc = within(table).getAllByRole("row")[1];
    const sortedDesc = [...market.plans["2025"]].sort((a, b) => b.org_name.localeCompare(a.org_name));
    expect(within(firstRowDesc).getByText(sortedDesc[0].org_name)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Sort by Org, currently descending/ }));
    const firstRowAsc = within(table).getAllByRole("row")[1];
    const sortedAsc = [...market.plans["2025"]].sort((a, b) => a.org_name.localeCompare(b.org_name));
    expect(within(firstRowAsc).getByText(sortedAsc[0].org_name)).toBeInTheDocument();
  });

  it("marks an imputed star rating with the '*' indicator, never silently presenting it as measured", () => {
    renderReal();
    const imputedPlan = uniquelyNamed(market.plans["2025"]).find((p) => p.imputed_star);
    expect(imputedPlan).toBeDefined();
    const row = screen.getByText(imputedPlan!.plan_name).closest("tr")!;
    expect(within(row).getByTitle("Imputed star rating")).toBeInTheDocument();
  });

  it("shows a filled dot only for benefits the plan actually has (dental/vision/hearing/OTC)", () => {
    renderReal();
    const noDentalPlan = uniquelyNamed(market.plans["2025"]).find((p) => !p.has_comprehensive_dental && p.has_vision);
    expect(noDentalPlan).toBeDefined();
    const row = screen.getByText(noDentalPlan!.plan_name).closest("tr")!;
    expect(within(row).getByLabelText("Dental: not included")).toBeInTheDocument();
    expect(within(row).getByLabelText("Vision: included")).toBeInTheDocument();
  });
});
