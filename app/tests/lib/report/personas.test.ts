import { describe, expect, it } from "vitest";

import type { ArchetypeDisplayRecord, MarketPlan, PersonaRecord } from "@/lib/data/types";
import {
  buildPersonaCards,
  buildPersonaLookup,
  buildPlanLookup,
  placeholderPersonaName,
} from "@/lib/report/personas";

function makeArchetype(overrides: Partial<ArchetypeDisplayRecord> = {}): ArchetypeDisplayRecord {
  return {
    id: "a75_84-middle-mixed-brand_loyal",
    demographics: { age_band: "75-84", income_tier: "middle", race_eth: "mixed" },
    segment: "brand_loyal",
    dual_proxy: false,
    weight: 19688.007588,
    share_of_population: 0.0255126469,
    traits: ["values stability", "prefers familiar plans"],
    prior_outside_share: 0.4,
    top_prior_plans: [{ plan_key: "H0028-023", prior_prob: 0.05 }],
    ...overrides,
  };
}

function makePlan(overrides: Partial<MarketPlan> = {}): MarketPlan {
  return {
    plan_key: "H0028-023",
    org_name: "Humana",
    plan_name: "Humana Gold Plus H0028-023 (HMO)",
    plan_type: "HMO",
    is_ppo: false,
    snp_type: "Not Applicable",
    premium_total: 17,
    moop_inn: 6700,
    star_rating: 3.5,
    has_comprehensive_dental: true,
    has_vision: true,
    has_hearing_aids: true,
    has_otc_or_flex: true,
    imputed_moop: false,
    imputed_star: false,
    enrollment: 292,
    ...overrides,
  };
}

describe("placeholderPersonaName", () => {
  it("matches the spec's 'Archetype: 75-84 - middle income - brand loyal' shape", () => {
    expect(placeholderPersonaName(makeArchetype())).toBe("Archetype: 75-84 - middle income - brand loyal");
  });

  it("falls back to 'mixed income' when income_tier is null", () => {
    const archetype = makeArchetype({ demographics: { age_band: "65-69", income_tier: null, race_eth: null } });
    expect(placeholderPersonaName(archetype)).toBe("Archetype: 65-69 - mixed income - brand loyal");
  });
});

describe("buildPlanLookup / buildPersonaLookup", () => {
  it("keys plans by plan_key", () => {
    const lookup = buildPlanLookup([makePlan()]);
    expect(lookup.get("H0028-023")?.org_name).toBe("Humana");
  });

  it("keys personas by their id (the archetype id, per run_persona_pass.py)", () => {
    const persona: PersonaRecord = { id: "a75_84-middle-mixed-brand_loyal", name: "Dorothy", backstory: "..." };
    const lookup = buildPersonaLookup([persona]);
    expect(lookup.get("a75_84-middle-mixed-brand_loyal")?.name).toBe("Dorothy");
  });
});

describe("buildPersonaCards", () => {
  it("uses the placeholder name and hasBackstory=false when no persona exists for the archetype", () => {
    const cards = buildPersonaCards([makeArchetype()], buildPlanLookup([makePlan()]), new Map());
    expect(cards).toHaveLength(1);
    expect(cards[0].hasBackstory).toBe(false);
    expect(cards[0].backstory).toBeNull();
    expect(cards[0].name).toBe("Archetype: 75-84 - middle income - brand loyal");
  });

  it("resolves top_prior_plans against the plan lookup for a readable label, without duplicating the org name", () => {
    const cards = buildPersonaCards([makeArchetype()], buildPlanLookup([makePlan()]), new Map());
    expect(cards[0].topPlans).toEqual([{ planKey: "H0028-023", label: "Humana Gold Plus H0028-023 (HMO)" }]);
  });

  it("falls back to concatenation when plan_name does not already start with org_name", () => {
    const plan = makePlan({ org_name: "UnitedHealthcare", plan_name: "AARP Medicare Advantage Choice" });
    const cards = buildPersonaCards([makeArchetype()], buildPlanLookup([plan]), new Map());
    expect(cards[0].topPlans).toEqual([{ planKey: "H0028-023", label: "UnitedHealthcare AARP Medicare Advantage Choice" }]);
  });

  it("falls back to the bare plan_key when a prior plan isn't in the lookup", () => {
    const cards = buildPersonaCards([makeArchetype()], new Map(), new Map());
    expect(cards[0].topPlans).toEqual([{ planKey: "H0028-023", label: "H0028-023" }]);
  });

  it("uses the persona's real name/backstory once one exists for the archetype", () => {
    const persona: PersonaRecord = {
      id: "a75_84-middle-mixed-brand_loyal",
      name: "Dorothy R.",
      backstory: "Dorothy has kept the same plan for six years.",
      rationale: "Strong inertia, low switching propensity.",
    };
    const personaByArchetypeId = buildPersonaLookup([persona]);
    const cards = buildPersonaCards([makeArchetype()], new Map(), personaByArchetypeId);
    expect(cards[0].hasBackstory).toBe(true);
    expect(cards[0].name).toBe("Dorothy R.");
    expect(cards[0].backstory).toBe("Dorothy has kept the same plan for six years.");
    expect(cards[0].rationale).toBe("Strong inertia, low switching propensity.");
  });

  it("carries weight/share/segment/traits through for the card badges", () => {
    const cards = buildPersonaCards([makeArchetype()], new Map(), new Map());
    expect(cards[0].weightLabel).toBe("19,688 people");
    expect(cards[0].shareOfPopulationLabel).toBe("2.55%");
    expect(cards[0].segmentLabel).toBe("Brand loyal");
    expect(cards[0].traits).toEqual(["values stability", "prefers familiar plans"]);
  });
});
