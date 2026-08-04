// @vitest-environment jsdom
/**
 * `LiveLlmButton` is only ever mounted by `app/page.tsx` when
 * `ENABLE_LIVE_LLM === 'true'` -- but the component itself has no idea
 * whether that's true; it always renders, and its `/api/persona-live` call
 * always exists to be made. So "the feature-disabled default path" this
 * component actually needs to handle gracefully is: the request comes back
 * 501 with a `reason` (the real, exact response
 * `app/api/persona-live/route.ts` returns in the default zero-env-var
 * build, per that route's own docstring) -- the button must show that
 * reason as a plain "Not available: ..." message, never crash, and never
 * fabricate a persona.
 *
 * `fetch` is always mocked here (same convention as
 * `tests/api/persona-live.test.ts`) -- no real network call is made.
 */
import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { LiveLlmButton } from "@/components/report/LiveLlmButton";
import { archetypesDisplay } from "@/lib/data/loaders";
import { formatAgeBand, humanizeToken } from "@/lib/format";

const FIRST_ARCHETYPE = archetypesDisplay.archetypes[0];
const FIRST_ARCHETYPE_LABEL = `${formatAgeBand(FIRST_ARCHETYPE.demographics.age_band)} - ${
  FIRST_ARCHETYPE.demographics.income_tier ? `${humanizeToken(FIRST_ARCHETYPE.demographics.income_tier)} income` : "Mixed income"
} - ${humanizeToken(FIRST_ARCHETYPE.segment)}`;

afterEach(() => {
  vi.restoreAllMocks();
});

describe("LiveLlmButton -- idle render", () => {
  it("renders idle, with the real archetype roster populated and the first one selected, no error/success blocks shown", () => {
    render(<LiveLlmButton />);
    const select = screen.getByLabelText("Archetype") as HTMLSelectElement;
    expect(select.value).toBe(FIRST_ARCHETYPE.id);
    // Two archetypes can share the same label (age band/income/segment
    // differ only by race_eth, which isn't part of the label) -- so look
    // this option up by its unique `value`, not by accessible name.
    const firstOption = select.querySelector(`option[value="${FIRST_ARCHETYPE.id}"]`);
    expect(firstOption?.textContent).toBe(FIRST_ARCHETYPE_LABEL);
    expect(select.options.length).toBe(archetypesDisplay.archetypes.length);

    const button = screen.getByRole("button", { name: "Generate live persona (experimental)" });
    expect(button).toBeEnabled();
    expect(screen.queryByText(/Not available:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/live, not saved to personas\.json/)).not.toBeInTheDocument();
  });
});

describe("LiveLlmButton -- feature-disabled default path (real 501 shape)", () => {
  it("shows the server's exact gate reason as 'Not available: ...' after a click, without crashing", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ reason: "ENABLE_LIVE_LLM is not set to 'true'." }), {
        status: 501,
        headers: { "content-type": "application/json" },
      }),
    );

    render(<LiveLlmButton />);
    fireEvent.click(screen.getByRole("button", { name: "Generate live persona (experimental)" }));

    expect(await screen.findByText("Not available: ENABLE_LIVE_LLM is not set to 'true'.")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/persona-live",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ archetypeId: FIRST_ARCHETYPE.id }) }),
    );
    // No persona is fabricated on a gate failure.
    expect(screen.queryByText(/live, not saved to personas\.json/)).not.toBeInTheDocument();
    // Button returns to clickable, not stuck in "Requesting…".
    expect(screen.getByRole("button", { name: "Generate live persona (experimental)" })).toBeEnabled();
  });

  it("shows a loading state (disabled controls, 'Requesting…') while the request is in flight", async () => {
    let resolveFetch!: (value: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    render(<LiveLlmButton />);
    fireEvent.click(screen.getByRole("button", { name: "Generate live persona (experimental)" }));

    expect(await screen.findByRole("button", { name: "Requesting…" })).toBeDisabled();
    expect(screen.getByLabelText("Archetype")).toBeDisabled();

    resolveFetch(new Response(JSON.stringify({ reason: "ENABLE_LIVE_LLM is not set to 'true'." }), { status: 501 }));
    expect(await screen.findByText(/Not available:/)).toBeInTheDocument();
  });

  it("falls back to a generic error message if fetch itself rejects (e.g. offline), rather than crashing", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    render(<LiveLlmButton />);
    fireEvent.click(screen.getByRole("button", { name: "Generate live persona (experimental)" }));

    expect(await screen.findByText("Not available: Request failed.")).toBeInTheDocument();
  });
});

describe("LiveLlmButton -- success path (mocked, not a real OpenAI call)", () => {
  it("renders the returned name/backstory and labels it clearly as live/unsaved", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ name: "Jordan Whitfield", backstory: "A short fictional backstory." }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    render(<LiveLlmButton />);
    fireEvent.click(screen.getByRole("button", { name: "Generate live persona (experimental)" }));

    expect(await screen.findByText("A short fictional backstory.")).toBeInTheDocument();
    expect(screen.getByText("Jordan Whitfield", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/live, not saved to personas\.json/)).toBeInTheDocument();
  });
});
