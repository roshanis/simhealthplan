/**
 * POST /api/persona-live -- optional live-LLM persona narrative stub.
 *
 * The report's "Live LLM" button (see `components/report/PersonaCards.tsx`)
 * only renders when `ENABLE_LIVE_LLM === "true"`, so a request here should
 * be rare in the default (zero-env-var) build/deploy. Either way, this
 * route only ever implements the gate:
 *
 *   - flag off, or no OPENAI_API_KEY configured -> 501 explaining which
 *     precondition is missing.
 *   - flag on AND a key is configured -> still 501: the actual live call is
 *     a TODO for a later phase (ticket: wire a real OpenAI persona-narrative
 *     call here, budget-capped like `pipeline/llm/run_persona_pass.py`).
 *     Never silently succeeds with fabricated output.
 */

import { NextResponse } from "next/server";

export async function POST(): Promise<Response> {
  const liveLlmEnabled = process.env.ENABLE_LIVE_LLM === "true";
  const hasApiKey = Boolean(process.env.OPENAI_API_KEY);

  if (!liveLlmEnabled) {
    return NextResponse.json({ reason: "ENABLE_LIVE_LLM is not set to 'true'." }, { status: 501 });
  }
  if (!hasApiKey) {
    return NextResponse.json({ reason: "OPENAI_API_KEY is not configured." }, { status: 501 });
  }

  // TODO(phase-8): wire the real live-LLM persona call. Intentionally
  // unimplemented -- always 501 until then, even when preconditions pass.
  return NextResponse.json({ reason: "not yet wired" }, { status: 501 });
}
