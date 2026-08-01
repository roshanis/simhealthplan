/**
 * POST /api/scenario -- recomputes 2025 plan shares under a set of
 * counterfactual plan-attribute changes, via the existing TS choice-model
 * engine (`lib/choice-model/`) run against `scenario_inputs.json`.
 *
 * Pure math, no LLM, no external calls, no filesystem I/O at request time:
 * `scenario_inputs.json` and `coefficients.json` are static ES imports
 * (see `lib/data/loaders.ts`), inlined into the server bundle at build
 * time. POST handlers are never cached by Next.js (only `GET` opts into
 * caching), so every request recomputes fresh -- which is the point of a
 * live scenario demo.
 */

import { NextResponse } from "next/server";

import type { Archetype, Plan } from "@/lib/choice-model/types";
import { coefficients, scenarioInputs } from "@/lib/data/loaders";
import { runScenario } from "@/lib/scenario/runScenario";
import { ScenarioRequestSchema } from "@/lib/scenario/schema";

const basePlans = scenarioInputs.plans as unknown as Plan[];
const archetypes = scenarioInputs.archetypes as unknown as Archetype[];
const outsideOptionKey = scenarioInputs.outside_option_key;
const knownPlanKeys = new Set(basePlans.map((p) => p.plan_key));

export async function POST(request: Request): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Request body must be valid JSON." }, { status: 400 });
  }

  const parsed = ScenarioRequestSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid scenario request.", issues: parsed.error.issues },
      { status: 400 },
    );
  }

  const unknownPlanKeys = [...new Set(parsed.data.changes.map((c) => c.plan_key))].filter(
    (key) => !knownPlanKeys.has(key),
  );
  if (unknownPlanKeys.length > 0) {
    return NextResponse.json(
      { error: `Unknown plan_key(s) not in the 2025 roster: ${unknownPlanKeys.join(", ")}` },
      { status: 400 },
    );
  }

  const result = runScenario(archetypes, basePlans, coefficients, parsed.data.changes, outsideOptionKey, {
    draws: parsed.data.draws,
    seed: parsed.data.seed,
  });

  return NextResponse.json(result);
}
