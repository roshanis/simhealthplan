import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { POST } from "@/app/api/persona-live/route";

const ORIGINAL_ENABLE = process.env.ENABLE_LIVE_LLM;
const ORIGINAL_KEY = process.env.OPENAI_API_KEY;

function restoreEnv() {
  if (ORIGINAL_ENABLE === undefined) delete process.env.ENABLE_LIVE_LLM;
  else process.env.ENABLE_LIVE_LLM = ORIGINAL_ENABLE;
  if (ORIGINAL_KEY === undefined) delete process.env.OPENAI_API_KEY;
  else process.env.OPENAI_API_KEY = ORIGINAL_KEY;
}

describe("POST /api/persona-live", () => {
  beforeEach(() => {
    delete process.env.ENABLE_LIVE_LLM;
    delete process.env.OPENAI_API_KEY;
  });
  afterEach(restoreEnv);

  it("returns 501 with a flag-specific reason when ENABLE_LIVE_LLM is unset (the default, zero-env-var build)", async () => {
    const response = await POST();
    expect(response.status).toBe(501);
    const body = await response.json();
    expect(body.reason).toMatch(/ENABLE_LIVE_LLM/);
  });

  it("returns 501 with a key-specific reason when the flag is on but no OPENAI_API_KEY is set", async () => {
    process.env.ENABLE_LIVE_LLM = "true";
    const response = await POST();
    expect(response.status).toBe(501);
    const body = await response.json();
    expect(body.reason).toMatch(/OPENAI_API_KEY/);
  });

  it("still returns 501 ('not yet wired') even when both preconditions are satisfied -- the live path is an intentional stub", async () => {
    process.env.ENABLE_LIVE_LLM = "true";
    process.env.OPENAI_API_KEY = "sk-test-not-real";
    const response = await POST();
    expect(response.status).toBe(501);
    const body = await response.json();
    expect(body.reason).toBe("not yet wired");
  });
});
