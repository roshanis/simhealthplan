/**
 * Minimal fetch-based OpenAI Chat Completions client for the live
 * persona-narrative route.
 *
 * Deliberately NOT the `openai` npm SDK -- `app/package.json` has zero LLM
 * dependencies today, and a single structured-output POST doesn't warrant
 * pulling in a new package (and its lockfile churn) when `fetch` already
 * does the job. This is the same REST API `pipeline/llm/client.py` talks to
 * via the Python `openai` SDK (`client.chat.completions.create(...,
 * response_format={"type": "json_schema", ...})`); the request body shape
 * here is the wire-level equivalent of that call, not a different API.
 *
 * Unlike `pipeline/llm/client.py`, there is deliberately NO cache and NO
 * multi-call retry/budget bookkeeping here -- this route serves exactly one
 * interactive click, so "a single call per request" (this module makes
 * exactly one `fetch`) plus a hard timeout is the entire cost-control
 * story. Retrying a slow/rate-limited upstream from a live button click
 * would just make one click cost 2-3x; better to fail fast and let the
 * user click again.
 */

import { MAX_OUTPUT_TOKENS, OPENAI_CHAT_COMPLETIONS_URL, REQUEST_TIMEOUT_MS, TEMPERATURE } from "@/lib/llm/config";
import type { PersonaNarrativeResponseSchema } from "@/lib/llm/personaPrompt";

/** Distinguishes failure modes so the route can pick an accurate HTTP
 * status (504 for timeout, 502 for everything else upstream) without ever
 * forwarding raw upstream error bodies -- those can echo request details
 * (including, in some providers' error payloads, fragments of the request)
 * back to the caller, which is the one thing the route must never do. */
export type LiveLlmErrorKind = "timeout" | "network" | "http" | "empty_response" | "unparseable_response";

export class LiveLlmUpstreamError extends Error {
  readonly kind: LiveLlmErrorKind;
  /** Upstream HTTP status, when `kind === "http"`. Never the response body. */
  readonly upstreamStatus?: number;

  constructor(kind: LiveLlmErrorKind, message: string, upstreamStatus?: number) {
    super(message);
    this.name = "LiveLlmUpstreamError";
    this.kind = kind;
    this.upstreamStatus = upstreamStatus;
  }
}

export interface RequestPersonaNarrativeArgs {
  apiKey: string;
  model: string;
  promptKey: string;
  system: string;
  user: string;
  responseSchema: PersonaNarrativeResponseSchema;
}

export interface PersonaNarrativeResult {
  name: string;
  backstory: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Sanitizes an OpenAI json_schema `name` the same way
 * `pipeline/llm/client.py`'s `_schema_name` does (alnum/underscore/hyphen
 * only, non-empty, <=64 chars) -- the field has the same validity
 * constraints on both sides of this API. */
function schemaName(promptKey: string): string {
  const name = promptKey.replace(/[^a-zA-Z0-9_-]/g, "_").replace(/^_+|_+$/g, "");
  return (name || "response").slice(0, 64);
}

/**
 * Makes exactly one Chat Completions request with strict structured
 * output, enforcing the module-level timeout/token guards. Throws
 * `LiveLlmUpstreamError` on any failure -- callers should never see a raw
 * exception, a stack trace, or upstream response text past what this
 * function chooses to summarize.
 */
export async function requestPersonaNarrative({
  apiKey,
  model,
  promptKey,
  system,
  user,
  responseSchema,
}: RequestPersonaNarrativeArgs): Promise<PersonaNarrativeResult> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(OPENAI_CHAT_COMPLETIONS_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        temperature: TEMPERATURE,
        max_tokens: MAX_OUTPUT_TOKENS,
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        response_format: {
          type: "json_schema",
          json_schema: {
            name: schemaName(promptKey),
            schema: responseSchema,
            strict: true,
          },
        },
      }),
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new LiveLlmUpstreamError("timeout", `OpenAI request did not complete within ${REQUEST_TIMEOUT_MS}ms.`);
    }
    throw new LiveLlmUpstreamError("network", "Could not reach the OpenAI API.");
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    // Deliberately not forwarding `await response.text()` -- OpenAI error
    // bodies can be verbose and are not vetted for anything safe to echo
    // back to a browser caller. Status code is enough for the UI to show a
    // useful "upstream failed" message.
    throw new LiveLlmUpstreamError("http", `OpenAI API responded with HTTP ${response.status}.`, response.status);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new LiveLlmUpstreamError("unparseable_response", "OpenAI response body was not valid JSON.");
  }

  const content = extractMessageContent(payload);
  if (content === null) {
    throw new LiveLlmUpstreamError("empty_response", "OpenAI response did not include message content.");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    throw new LiveLlmUpstreamError("unparseable_response", "OpenAI response content was not valid JSON.");
  }

  if (!isRecord(parsed) || typeof parsed.name !== "string" || typeof parsed.backstory !== "string") {
    throw new LiveLlmUpstreamError(
      "unparseable_response",
      "OpenAI response JSON did not match the required {name, backstory} schema.",
    );
  }

  return { name: parsed.name, backstory: parsed.backstory };
}

/** Pulls `choices[0].message.content` out of a Chat Completions response
 * body, tolerant of an unexpected/absent shape (returns `null` rather than
 * throwing -- the caller turns that into a typed `LiveLlmUpstreamError`). */
function extractMessageContent(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  const choices = payload.choices;
  if (!Array.isArray(choices) || choices.length === 0) return null;
  const first = choices[0];
  if (!isRecord(first)) return null;
  const message = first.message;
  if (!isRecord(message)) return null;
  // A refusal (OpenAI's structured-refusal field, mirrored from
  // `pipeline/llm/client.py`'s `message.refusal` check) means no usable
  // content even if `content` happens to be non-null.
  if (typeof message.refusal === "string" && message.refusal.length > 0) return null;
  const content = message.content;
  return typeof content === "string" ? content : null;
}
