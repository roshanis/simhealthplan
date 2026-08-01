/**
 * Pure view-model builder for the "Meet the market" persona cards section.
 *
 * Until `data/processed/personas.json` exists (the LLM backstory pass hasn't
 * run yet, see `pipeline/llm/run_persona_pass.py`), every card falls back to
 * a deterministic placeholder name built from the archetype's own fields --
 * exactly the `"Archetype: 75-84 - middle income - brand loyal"` shape the
 * spec calls for. Once `personas.json` exists (`personasAvailable === true`
 * / a matching `PersonaRecord` is found), the card's name/backstory/
 * rationale come from the LLM-authored persona instead.
 */

import { formatAgeBand, formatCount, formatPercent, humanizeToken, planLabel } from "@/lib/format";
import type { ArchetypeDisplayRecord, MarketPlan, PersonaRecord } from "@/lib/data/types";

export interface PersonaCardTopPlan {
  planKey: string;
  label: string;
}

export interface PersonaCardViewModel {
  id: string;
  name: string;
  hasBackstory: boolean;
  backstory: string | null;
  rationale: string | null;
  ageBandLabel: string;
  incomeTierLabel: string;
  raceEthLabel: string;
  segmentLabel: string;
  dualEligibleProxy: boolean;
  weightLabel: string;
  shareOfPopulationLabel: string;
  traits: string[];
  topPlans: PersonaCardTopPlan[];
  outsideShareLabel: string;
}

/** `"Archetype: 75-84 - middle income - brand loyal"`-shaped placeholder
 * name, built entirely from `archetypes.json` fields (no LLM dependency). */
export function placeholderPersonaName(archetype: ArchetypeDisplayRecord): string {
  const income = archetype.demographics.income_tier ? `${archetype.demographics.income_tier} income` : "mixed income";
  return `Archetype: ${archetype.demographics.age_band} - ${income} - ${humanizeToken(archetype.segment).toLowerCase()}`;
}

function resolvePlanLabel(plan: MarketPlan | undefined, planKey: string): string {
  if (!plan) return planKey;
  return planLabel(plan.org_name, plan.plan_name) || planKey;
}

/**
 * Builds one card view-model per archetype. `plansByKey` (the 2024 roster,
 * keyed by `plan_key`) resolves each archetype's `top_prior_plans` into
 * readable labels; a missing lookup falls back to the bare plan_key rather
 * than dropping the row. `personaByArchetypeId` is an empty map until
 * `personas.json`'s `available` flag flips true.
 */
export function buildPersonaCards(
  archetypes: ArchetypeDisplayRecord[],
  plansByKey: Map<string, MarketPlan>,
  personaByArchetypeId: Map<string, PersonaRecord>,
): PersonaCardViewModel[] {
  return archetypes.map((archetype) => {
    const persona = personaByArchetypeId.get(archetype.id);
    const hasBackstory = Boolean(persona?.backstory);

    return {
      id: archetype.id,
      name: hasBackstory && typeof persona?.name === "string" ? (persona.name as string) : placeholderPersonaName(archetype),
      hasBackstory,
      backstory: hasBackstory ? (persona!.backstory as string) : null,
      rationale: typeof persona?.rationale === "string" ? (persona!.rationale as string) : null,
      ageBandLabel: formatAgeBand(archetype.demographics.age_band),
      incomeTierLabel: archetype.demographics.income_tier ? humanizeToken(archetype.demographics.income_tier) : "Mixed",
      raceEthLabel: archetype.demographics.race_eth ? humanizeToken(archetype.demographics.race_eth) : "Mixed",
      segmentLabel: humanizeToken(archetype.segment),
      dualEligibleProxy: archetype.dual_proxy,
      weightLabel: `${formatCount(archetype.weight)} people`,
      shareOfPopulationLabel: formatPercent(archetype.share_of_population, 2),
      traits: archetype.traits,
      topPlans: archetype.top_prior_plans.map((p) => ({
        planKey: p.plan_key,
        label: resolvePlanLabel(plansByKey.get(p.plan_key), p.plan_key),
      })),
      outsideShareLabel: formatPercent(archetype.prior_outside_share, 1),
    };
  });
}

/** `market.json`'s 2024 plan roster -> `plan_key` lookup map, for resolving
 * archetype `top_prior_plans` entries to display labels. */
export function buildPlanLookup(plans2024: MarketPlan[]): Map<string, MarketPlan> {
  return new Map(plans2024.map((plan) => [plan.plan_key, plan]));
}

/** `personas.json`'s flat `personas` array -> archetype-id lookup map
 * (each persona's `id` field IS the archetype id it was generated for --
 * see `pipeline/llm/run_persona_pass.py`). */
export function buildPersonaLookup(personas: PersonaRecord[]): Map<string, PersonaRecord> {
  return new Map(personas.map((p) => [p.id, p]));
}
