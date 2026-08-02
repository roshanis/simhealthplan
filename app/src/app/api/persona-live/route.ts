/**
 * POST /api/persona-live -- live-LLM persona narrative for one archetype.
 *
 * The report's "Live LLM" button (see `components/report/LiveLlmButton.tsx`)
 * only renders when `ENABLE_LIVE_LLM === "true"`, so a request here should
 * be rare in the default (zero-env-var) build/deploy -- that default build
 * never renders the button and therefore never issues this request. Either
 * way, this route enforces its own gate independent of the UI (a direct
 * `curl` must be gated exactly the same as a click):
 *
 *   - flag off -> 501, reason names `ENABLE_LIVE_LLM`.
 *   - flag on, no `OPENAI_API_KEY` configured -> 501 (not enabled at all --
 *     nothing was attempted), a DISTINCT reason naming `OPENAI_API_KEY`.
 *     (501 "Not Implemented" rather than 503 "Service Unavailable": from
 *     this deployment's point of view the feature simply isn't turned on,
 *     the same as the flag-off case, not a transiently-down dependency.)
 *   - flag on AND a key configured, but the request body is missing/invalid
 *     JSON, fails the `PersonaLiveRequestSchema` zod check, or names an
 *     `archetypeId` outside `archetypes.json`'s roster -> 400, mirroring
 *     the strictness of `app/api/scenario/route.ts` (see that route's
 *     docstring: unknown/malformed input is always a 400 with an `error` +
 *     optional `issues`, never a best-effort guess).
 *   - flag on, keyed, valid request -> exactly one OpenAI Chat Completions
 *     call (`lib/llm/openaiClient.ts`), budget-capped by an ~20s
 *     AbortController timeout and a bounded `max_tokens`
 *     (`lib/llm/config.ts`), using the same model id and the same
 *     system/user prompt wording as the batch BACKSTORY pass
 *     (`pipeline/llm/persona_prompts.py`'s `build_backstory_prompt`, mirrored
 *     in `lib/llm/personaPrompt.ts`) so a live narrative reads as the same
 *     voice as the committed `data/processed/personas.json` backstories,
 *     not a different one-off voice.
 *   - upstream timeout -> 504; any other upstream failure (network error,
 *     non-2xx, unparseable/malformed structured output) -> 502. Both cases
 *     return a clean, generic `error` string -- never a stack trace, never
 *     `OPENAI_API_KEY`, and never raw upstream response text (which is not
 *     vetted for anything safe to echo back to a browser caller; see
 *     `lib/llm/openaiClient.ts`'s `LiveLlmUpstreamError` docstring).
 *
 * Never silently succeeds with fabricated output: every non-200 response
 * above is a real "this didn't happen" signal, and the only way to get a
 * persona narrative back is a real, successful upstream call.
 */

import { NextResponse } from "next/server";

import { archetypesDisplay } from "@/lib/data/loaders";
import { resolveOpenAiModel } from "@/lib/llm/config";
import { LiveLlmUpstreamError, requestPersonaNarrative } from "@/lib/llm/openaiClient";
import { buildPersonaNarrativePrompt } from "@/lib/llm/personaPrompt";
import { PersonaLiveRequestSchema } from "@/lib/llm/schema";

const PROMPT_KEY = "live_backstory_v1";

const archetypesById = new Map(archetypesDisplay.archetypes.map((archetype) => [archetype.id, archetype]));

/** Maps an upstream failure to the HTTP status + safe body this route
 * returns. Kept as a pure function so the mapping itself is testable
 * without needing a real `LiveLlmUpstreamError` thrown through `fetch`. */
function upstreamErrorResponse(err: LiveLlmUpstreamError): Response {
  const status = err.kind === "timeout" ? 504 : 502;
  return NextResponse.json({ error: err.message }, { status });
}

export async function POST(request: Request): Promise<Response> {
  const liveLlmEnabled = process.env.ENABLE_LIVE_LLM === "true";
  const apiKey = process.env.OPENAI_API_KEY;

  if (!liveLlmEnabled) {
    return NextResponse.json({ reason: "ENABLE_LIVE_LLM is not set to 'true'." }, { status: 501 });
  }
  if (!apiKey) {
    return NextResponse.json({ reason: "OPENAI_API_KEY is not configured." }, { status: 501 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Request body must be valid JSON." }, { status: 400 });
  }

  const parsed = PersonaLiveRequestSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid persona-live request.", issues: parsed.error.issues },
      { status: 400 },
    );
  }

  const archetype = archetypesById.get(parsed.data.archetypeId);
  if (!archetype) {
    return NextResponse.json(
      { error: `Unknown archetypeId (not in the current archetypes.json roster): ${parsed.data.archetypeId}` },
      { status: 400 },
    );
  }

  const { system, user, responseSchema } = buildPersonaNarrativePrompt(archetype);

  try {
    const narrative = await requestPersonaNarrative({
      apiKey,
      model: resolveOpenAiModel(),
      promptKey: PROMPT_KEY,
      system,
      user,
      responseSchema,
    });

    // Single call per request: this is the only `requestPersonaNarrative`
    // invocation on this code path, and there is no retry loop here (unlike
    // `pipeline/llm/client.py`'s corrective-retry + tenacity layers) --
    // a live button click either gets one clean answer or a clear error.
    return NextResponse.json({
      archetypeId: archetype.id,
      name: narrative.name,
      backstory: narrative.backstory,
    });
  } catch (err) {
    if (err instanceof LiveLlmUpstreamError) {
      return upstreamErrorResponse(err);
    }
    // Defensive fallback for a genuinely unexpected throw (should not
    // happen -- `requestPersonaNarrative` only ever throws
    // `LiveLlmUpstreamError`). Still never leaks a stack trace or the key.
    return NextResponse.json({ error: "Unexpected error generating the live persona narrative." }, { status: 502 });
  }
}
