/**
 * Constants for the live-LLM persona-narrative call made by
 * `app/api/persona-live`. Kept in one place so the route handler and its
 * tests agree on the same numbers.
 *
 * `DEFAULT_OPENAI_MODEL` intentionally mirrors `pipeline/config/settings.py`'s
 * `Settings.OPENAI_MODEL` default ("gpt-5.6-luna") so the live, one-off,
 * browser-triggered narrative uses the same model id as the batch
 * `pipeline/llm/run_persona_pass.py` backstory pass -- this is a live
 * preview of the same voice, not a different model with different
 * behavior. Like the pipeline side, it can be overridden with the
 * `OPENAI_MODEL` env var without touching code.
 */

export const DEFAULT_OPENAI_MODEL = "gpt-5.6-luna";

export function resolveOpenAiModel(): string {
  return process.env.OPENAI_MODEL?.trim() || DEFAULT_OPENAI_MODEL;
}

/** REST endpoint for the Chat Completions API (see `pipeline/llm/client.py`,
 * which uses the equivalent `openai` Python SDK call against the same API).
 * Plain `fetch` is used here instead of the `openai` npm SDK so this route
 * adds zero new dependencies to the app bundle. */
export const OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions";

/**
 * Hard server-side cost/latency guards for this *live, request-time* call --
 * deliberately much tighter than the pipeline's batch budget
 * (`MAX_LLM_CALLS=500` across an entire county run), because this path is
 * triggered directly by a browser click and must never let one click hang a
 * request indefinitely or generate an unbounded bill.
 */

/** Abort the upstream call if it hasn't responded within this many ms. */
export const REQUEST_TIMEOUT_MS = 20_000;

/** Upper bound on generated tokens for one persona narrative -- a short
 * name + one paragraph backstory (see `pipeline/llm/persona_prompts.py`'s
 * `build_backstory_prompt` docstring: "one short paragraph (3-5
 * sentences)"), with headroom for the JSON wrapper. */
export const MAX_OUTPUT_TOKENS = 400;

/** Deterministic like the batch pass (`pipeline/llm/client.py` always uses
 * `temperature=0`) -- a live demo button producing a different persona on
 * every click for the same archetype would be confusing, not compelling. */
export const TEMPERATURE = 0;
