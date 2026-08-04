/**
 * TypeScript mirror of `pipeline/llm/persona_prompts.py`'s
 * `build_backstory_prompt` / `backstory_response_schema` -- the prompt used
 * by the batch `pipeline/llm/run_persona_pass.py` BACKSTORY pass that
 * produces `data/processed/personas.json`'s `name`/`backstory` fields (see
 * `lib/report/personas.ts`, which renders exactly those two fields on each
 * persona card).
 *
 * This live route intentionally reuses the *same* system/user prompt
 * wording (not a paraphrase) so a live-generated narrative reads as the
 * same voice as the committed batch personas, just regenerated on demand
 * for one archetype instead of all 80 up front. Only the CHOICE half of
 * the Python module (plan ranking / switching propensity) is out of scope
 * here -- this route generates a narrative, not a re-ranked choice.
 *
 * Kept intentionally free of any archetype UI-view-model type
 * (`PersonaCardViewModel`) -- this operates on the raw
 * `ArchetypeDisplayRecord` shape from `lib/data/types.ts`, same as
 * `archetypes.json` on disk, so it doesn't need the report page's derived
 * fields (weight labels, plan lookups, etc.) that have nothing to do with
 * prompting an LLM.
 */

import type { ArchetypeDisplayRecord } from "@/lib/data/types";

/** Mirrors `pipeline/llm/persona_prompts.py`'s `_RACE_ETH_LABELS` exactly
 * (including the "mixed" catch-all wording) so the same archetype produces
 * the same demographic framing whether narrated by the batch pass or this
 * live route. */
const RACE_ETH_LABELS: Record<string, string> = {
  asian_nh: "Asian, non-Hispanic",
  black_nh: "Black, non-Hispanic",
  hispanic: "Hispanic or Latino",
  other_multi_nh: "another race or multiple races, non-Hispanic",
  white_nh: "White, non-Hispanic",
  mixed: "a mixed/aggregated demographic group (this archetype is a catch-all, not one specific background)",
};

function raceEthLabel(raceEth: string | null): string {
  if (!raceEth) return "unspecified";
  return RACE_ETH_LABELS[raceEth] ?? raceEth;
}

export interface PersonaNarrativeResponseSchema {
  type: "object";
  properties: {
    name: { type: "string" };
    backstory: { type: "string" };
  };
  required: ["name", "backstory"];
  additionalProperties: false;
}

/** Byte-for-byte the same schema shape as `backstory_response_schema()` in
 * `pipeline/llm/persona_prompts.py`, translated to a TS object literal. */
export function personaNarrativeResponseSchema(): PersonaNarrativeResponseSchema {
  return {
    type: "object",
    properties: {
      name: { type: "string" },
      backstory: { type: "string" },
    },
    required: ["name", "backstory"],
    additionalProperties: false,
  };
}

export interface PersonaNarrativePrompt {
  system: string;
  user: string;
  responseSchema: PersonaNarrativeResponseSchema;
}

/** Builds the system/user prompt for one archetype's live persona
 * narrative. Wording mirrors `build_backstory_prompt` in
 * `pipeline/llm/persona_prompts.py` -- see that module's docstring for why
 * race/ethnicity is passed as demographic context but names must not be
 * mechanically derived from it. */
export function buildPersonaNarrativePrompt(archetype: ArchetypeDisplayRecord): PersonaNarrativePrompt {
  const traits = archetype.traits.length > 0 ? archetype.traits.join("; ") : "no distinguishing traits on file";
  const incomeTier = archetype.demographics.income_tier ?? "unspecified";
  const raceLabel = raceEthLabel(archetype.demographics.race_eth);

  const system =
    "You invent a single clearly fictional Medicare beneficiary persona for an internal " +
    "simulation demo -- not a real person, living or dead. Respond with a single JSON " +
    "object matching the required schema -- no prose outside the JSON.\n\n" +
    "Give the persona a first and last name that reflects the plausible, genuine name " +
    "diversity found within any real demographic group, WITHOUT stereotyping: do not " +
    "mechanically derive the name from the persona's race/ethnicity (e.g. do not always " +
    "assign a name that 'matches' that group, and do not treat race/ethnicity as a lookup " +
    "table for names). Choose a name the way real name diversity actually works -- varied, " +
    "and not mechanically predictable from any single demographic field below.\n\n" +
    "backstory is one short paragraph (3-5 sentences), third person, grounding the persona " +
    "in their age, income situation, and listed traits -- how they think about their health " +
    "coverage, their day-to-day life, and what matters to them in a Medicare Advantage plan. " +
    "Do not name specific real companies, real plan names, or real places beyond a generic " +
    "reference to living in Maricopa County, Arizona.";

  const user =
    `Archetype ID: ${archetype.id}\n` +
    `Age band: ${archetype.demographics.age_band}\n` +
    `Income tier: ${incomeTier}\n` +
    `Dual-eligible (Medicare + Medicaid) proxy: ${archetype.dual_proxy}\n` +
    `Race/ethnicity (demographic context only -- see system instructions on names): ${raceLabel}\n` +
    `Attitude segment: ${archetype.segment}\n` +
    `Traits: ${traits}`;

  return { system, user, responseSchema: personaNarrativeResponseSchema() };
}
