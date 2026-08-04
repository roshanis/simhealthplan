/**
 * POST /api/persona-live -- covers the full gate + live-call state machine:
 *
 *   flag off -> 501 (ENABLE_LIVE_LLM reason)
 *   flag on, no key -> 501 (distinct OPENAI_API_KEY reason)
 *   flag on + key, malformed JSON -> 400
 *   flag on + key, schema-invalid body (missing archetypeId) -> 400
 *   flag on + key, unknown archetypeId -> 400
 *   flag on + key, valid request -> exactly one OpenAI call (mocked), 200
 *     with the narrative
 *   flag on + key, upstream timeout / non-2xx -> 504 / 502, no upstream
 *     body text or API key ever echoed back
 *
 * `fetch` is ALWAYS mocked here -- there is no `OPENAI_API_KEY` in this
 * environment (and outbound hosts are policy-restricted), so a real network
 * call must never be attempted by this suite. The live path against the
 * real OpenAI API is therefore unverified by this test file; see
 * `lib/llm/openaiClient.ts` for the request it would make.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/persona-live/route";
import { archetypesDisplay } from "@/lib/data/loaders";

const ORIGINAL_ENABLE = process.env.ENABLE_LIVE_LLM;
const ORIGINAL_KEY = process.env.OPENAI_API_KEY;
const ORIGINAL_MODEL = process.env.OPENAI_MODEL;

const REAL_ARCHETYPE_ID = archetypesDisplay.archetypes[0].id;

function restoreEnv() {
  if (ORIGINAL_ENABLE === undefined) delete process.env.ENABLE_LIVE_LLM;
  else process.env.ENABLE_LIVE_LLM = ORIGINAL_ENABLE;
  if (ORIGINAL_KEY === undefined) delete process.env.OPENAI_API_KEY;
  else process.env.OPENAI_API_KEY = ORIGINAL_KEY;
  if (ORIGINAL_MODEL === undefined) delete process.env.OPENAI_MODEL;
  else process.env.OPENAI_MODEL = ORIGINAL_MODEL;
}

function postRequest(body?: unknown): Request {
  return new Request("http://localhost/api/persona-live", {
    method: "POST",
    headers: { "content-type": "application/json" },
    // `body: undefined` (the malformed-JSON case) intentionally sends a
    // non-JSON payload -- `""` -- so `request.json()` throws, exactly like
    // a truly malformed client request.
    body: body === undefined ? "not json" : JSON.stringify(body),
  });
}

/** Builds a Chat Completions-shaped success response body, matching what
 * `lib/llm/openaiClient.ts` parses out of `choices[0].message.content`. */
function fakeOpenAiSuccessResponse(name: string, backstory: string): Response {
  return new Response(
    JSON.stringify({
      id: "chatcmpl-fake",
      choices: [{ message: { content: JSON.stringify({ name, backstory }) } }],
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
}

describe("POST /api/persona-live", () => {
  beforeEach(() => {
    delete process.env.ENABLE_LIVE_LLM;
    delete process.env.OPENAI_API_KEY;
    delete process.env.OPENAI_MODEL;
    vi.restoreAllMocks();
  });
  afterEach(restoreEnv);

  it("returns 501 with a flag-specific reason when ENABLE_LIVE_LLM is unset (the default, zero-env-var build)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const response = await POST(postRequest({ archetypeId: REAL_ARCHETYPE_ID }));
    expect(response.status).toBe(501);
    const body = await response.json();
    expect(body.reason).toMatch(/ENABLE_LIVE_LLM/);
    // Gate failures must never even parse the body / touch the network.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("returns 501 with a distinct, key-specific reason when the flag is on but no OPENAI_API_KEY is set", async () => {
    process.env.ENABLE_LIVE_LLM = "true";
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const response = await POST(postRequest({ archetypeId: REAL_ARCHETYPE_ID }));
    expect(response.status).toBe(501);
    const body = await response.json();
    expect(body.reason).toMatch(/OPENAI_API_KEY/);
    expect(body.reason).not.toMatch(/ENABLE_LIVE_LLM/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  describe("with both preconditions satisfied", () => {
    beforeEach(() => {
      process.env.ENABLE_LIVE_LLM = "true";
      process.env.OPENAI_API_KEY = "sk-test-not-real";
    });

    it("returns 400 for a malformed (non-JSON) request body", async () => {
      const response = await POST(postRequest(undefined));
      expect(response.status).toBe(400);
      const body = await response.json();
      expect(body.error).toMatch(/JSON/i);
    });

    it("returns 400 when archetypeId is missing", async () => {
      const response = await POST(postRequest({}));
      expect(response.status).toBe(400);
      const body = await response.json();
      expect(body.error).toBeTruthy();
      expect(Array.isArray(body.issues)).toBe(true);
    });

    it("returns 400 for an archetypeId not in the archetypes.json roster", async () => {
      const response = await POST(postRequest({ archetypeId: "not-a-real-archetype-id" }));
      expect(response.status).toBe(400);
      const body = await response.json();
      expect(body.error).toMatch(/Unknown archetypeId/);
    });

    it("never makes a real network call for any 400/501 path (fetch stays unmocked and unused)", async () => {
      const fetchSpy = vi.spyOn(globalThis, "fetch");
      await POST(postRequest({}));
      await POST(postRequest({ archetypeId: "nope" }));
      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it("happy path: mocks fetch, makes exactly one OpenAI call, and returns the narrative", async () => {
      const fetchSpy = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(fakeOpenAiSuccessResponse("Jordan Whitfield", "A short fictional backstory."));

      const response = await POST(postRequest({ archetypeId: REAL_ARCHETYPE_ID }));

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const [url, init] = fetchSpy.mock.calls[0];
      expect(String(url)).toBe("https://api.openai.com/v1/chat/completions");
      expect(init?.method).toBe("POST");

      expect(response.status).toBe(200);
      const body = await response.json();
      expect(body).toEqual({
        archetypeId: REAL_ARCHETYPE_ID,
        name: "Jordan Whitfield",
        backstory: "A short fictional backstory.",
      });
    });

    it("sends the configured model id and the API key only in the Authorization header, never in a way the response can echo back", async () => {
      process.env.OPENAI_MODEL = "gpt-test-model";
      const fetchSpy = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValue(fakeOpenAiSuccessResponse("Name", "Backstory."));

      const response = await POST(postRequest({ archetypeId: REAL_ARCHETYPE_ID }));
      const [, init] = fetchSpy.mock.calls[0];
      const sentBody = JSON.parse(init!.body as string);
      expect(sentBody.model).toBe("gpt-test-model");

      const headers = init!.headers as Record<string, string>;
      expect(headers.authorization).toBe("Bearer sk-test-not-real");

      // The API key must never appear anywhere in the response the browser
      // receives, in any form (headers or body).
      const rawResponseText = JSON.stringify([...response.headers.entries()]) + JSON.stringify(await response.json());
      expect(rawResponseText).not.toContain("sk-test-not-real");
      expect(rawResponseText).not.toContain(process.env.OPENAI_API_KEY);
    });

    it("maps an upstream timeout (AbortError) to 504 with a clean, generic error", async () => {
      vi.spyOn(globalThis, "fetch").mockImplementation(() => {
        const err = new DOMException("The operation was aborted.", "AbortError");
        return Promise.reject(err);
      });

      const response = await POST(postRequest({ archetypeId: REAL_ARCHETYPE_ID }));
      expect(response.status).toBe(504);
      const body = await response.json();
      expect(typeof body.error).toBe("string");
      expect(body.error).not.toContain("sk-test-not-real");
    });

    it("maps a non-2xx upstream response to 502 without forwarding the upstream body text", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response("some verbose upstream error body that must never leak", { status: 500 }),
      );

      const response = await POST(postRequest({ archetypeId: REAL_ARCHETYPE_ID }));
      expect(response.status).toBe(502);
      const body = await response.json();
      expect(body.error).not.toContain("must never leak");
      expect(body.error).toMatch(/500/);
    });

    it("maps a malformed structured-output payload to 502 rather than fabricating a narrative", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(JSON.stringify({ choices: [{ message: { content: "not valid json" } }] }), { status: 200 }),
      );

      const response = await POST(postRequest({ archetypeId: REAL_ARCHETYPE_ID }));
      expect(response.status).toBe(502);
      const body = await response.json();
      expect(body.name).toBeUndefined();
      expect(body.backstory).toBeUndefined();
    });
  });
});
