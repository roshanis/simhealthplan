// @vitest-environment jsdom
/**
 * `PersonaCards` has two materially different states depending on whether
 * `data/processed/personas.json`'s LLM backstory pass has run yet
 * (`personasAvailable`). The REAL, committed `personas.json` ships with
 * `available: false` (the LLM pass hasn't run in this repo checkout), so
 * the "unavailable/degraded" suite below runs against that real artifact --
 * exactly the state a fresh clone of this repo actually renders today. The
 * "available" suite uses a hand-built view-model instead, since no real
 * persona records exist to read from.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { PersonaCards } from "@/components/report/PersonaCards";
import { archetypesDisplay, market, personas } from "@/lib/data/loaders";
import { buildPersonaCards, buildPersonaLookup, buildPlanLookup } from "@/lib/report/personas";
import type { PersonaCardViewModel } from "@/lib/report/personas";

const REAL_CARDS = buildPersonaCards(
  archetypesDisplay.archetypes,
  buildPlanLookup(market.plans["2024"]),
  buildPersonaLookup(personas.personas),
);
const REAL_SEGMENTS = Array.from(new Set(REAL_CARDS.map((c) => c.segmentLabel))).sort();
const REAL_AGE_BANDS = Array.from(new Set(REAL_CARDS.map((c) => c.ageBandLabel))).sort();

describe("PersonaCards -- personas.json unavailable (real, committed degraded state)", () => {
  it("really is the unavailable state in this checkout (sanity check the fixture itself)", () => {
    expect(personas.available).toBe(false);
    expect(personas.personas).toHaveLength(0);
  });

  it("shows the pending-LLM-pass banner and renders every card with a deterministic placeholder name, without crashing", () => {
    render(
      <PersonaCards cards={REAL_CARDS} personasAvailable={personas.available} segments={REAL_SEGMENTS} ageBands={REAL_AGE_BANDS} />,
    );
    expect(screen.getByText(/Persona backstories are/)).toBeInTheDocument();
    expect(screen.getByText(/pending the LLM pass/)).toBeInTheDocument();

    // First page (PAGE_SIZE=12) of the 80 real archetypes, all placeholders.
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings).toHaveLength(12);
    for (const heading of headings) {
      expect(heading.textContent).toMatch(/^Archetype: /);
    }
  });

  it("paginates via 'Show more' rather than rendering all 80 cards at once", () => {
    render(
      <PersonaCards cards={REAL_CARDS} personasAvailable={personas.available} segments={REAL_SEGMENTS} ageBands={REAL_AGE_BANDS} />,
    );
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(12);
    const showMore = screen.getByRole("button", { name: /Show more \(68 remaining\)/ });
    fireEvent.click(showMore);
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(24);
    expect(screen.getByRole("button", { name: /Show more \(56 remaining\)/ })).toBeInTheDocument();
  });

  it("expanding a card with no backstory shows the muted 'Backstory pending' status, never a fabricated narrative", () => {
    render(
      <PersonaCards cards={REAL_CARDS} personasAvailable={personas.available} segments={REAL_SEGMENTS} ageBands={REAL_AGE_BANDS} />,
    );
    const [firstCard] = screen.getAllByRole("heading", { level: 3 });
    const cardEl = firstCard.closest("div")!.parentElement as HTMLElement;
    fireEvent.click(within(cardEl).getByRole("button", { name: "Show more" }));
    expect(within(cardEl).getByText("Backstory pending")).toBeInTheDocument();
    expect(within(cardEl).getByText(/narrative backstory will/)).toBeInTheDocument();
  });

  it("the segment filter actually narrows the visible set and updates the count line", () => {
    render(
      <PersonaCards cards={REAL_CARDS} personasAvailable={personas.available} segments={REAL_SEGMENTS} ageBands={REAL_AGE_BANDS} />,
    );
    expect(screen.getByText("80 of 80 archetypes")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Attitude segment"), { target: { value: "Brand loyal" } });
    const expectedCount = REAL_CARDS.filter((c) => c.segmentLabel === "Brand loyal").length;
    expect(screen.getByText(`${expectedCount} of 80 archetypes`)).toBeInTheDocument();
  });
});

describe("PersonaCards -- personas available (hand-built, since no real available persona exists in this checkout)", () => {
  function makeAvailableCard(): PersonaCardViewModel {
    return {
      id: "a75_84-middle-mixed-brand_loyal",
      name: "Dorothy R.",
      hasBackstory: true,
      backstory: "Dorothy has kept the same plan for six years and dislikes change.",
      rationale: "Strong inertia, low switching propensity.",
      ageBandLabel: "75-84",
      incomeTierLabel: "Middle",
      raceEthLabel: "Mixed",
      segmentLabel: "Brand loyal",
      dualEligibleProxy: false,
      weightLabel: "19,688 people",
      shareOfPopulationLabel: "2.55%",
      traits: ["values stability", "prefers familiar plans"],
      topPlans: [{ planKey: "H0028-023", label: "Humana Gold Plus H0028-023 (HMO)" }],
      outsideShareLabel: "40.0%",
    };
  }

  it("does not show the pending-LLM-pass banner once personas are available", () => {
    render(<PersonaCards cards={[makeAvailableCard()]} personasAvailable segments={["Brand loyal"]} ageBands={["75-84"]} />);
    expect(screen.queryByText(/pending the LLM pass/)).not.toBeInTheDocument();
  });

  it("expanding a card with a real backstory shows the LLM name/backstory/rationale, not the placeholder or 'pending' badge", () => {
    render(<PersonaCards cards={[makeAvailableCard()]} personasAvailable segments={["Brand loyal"]} ageBands={["75-84"]} />);
    expect(screen.getByRole("heading", { level: 3, name: "Dorothy R." })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(screen.getByText("Dorothy has kept the same plan for six years and dislikes change.")).toBeInTheDocument();
    expect(screen.getByText(/Strong inertia, low switching propensity\./)).toBeInTheDocument();
    expect(screen.queryByText("Backstory pending")).not.toBeInTheDocument();
    expect(screen.getByText("Humana Gold Plus H0028-023 (HMO)")).toBeInTheDocument();
  });
});
