import { describe, expect, it } from "vitest";

import { POST } from "@/app/api/scenario/route";
import { scenarioInputs } from "@/lib/data/loaders";

function postRequest(body: unknown): Request {
  return new Request("http://localhost/api/scenario", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

const largestPlan = scenarioInputs.plans.reduce((biggest, plan) =>
  plan.enrollment > biggest.enrollment ? plan : biggest,
);

describe("POST /api/scenario -- end to end against real scenario_inputs.json", () => {
  it("premium -15 + dropping dental on the largest 2025 plan moves shares directionally and returns bracketing bounds, in well under 1s", async () => {
    const scenarioBody = {
      changes: [
        { plan_key: largestPlan.plan_key, field: "premium_total", delta: -15 },
        { plan_key: largestPlan.plan_key, field: "has_comprehensive_dental", set: false },
      ],
    };

    // The first call pays one-off costs this budget is not meant to police:
    // module init, the lazy `scenario_inputs.json` parse, and V8's cold JIT.
    // Timing it made the assertion flake (1.5-3s) whenever vitest ran files in
    // parallel and the CPU was contended -- a false failure about the machine,
    // not about the engine. So: warm up once untimed, then take the BEST of
    // three warm runs. Best-of-N is the right statistic here because scheduler
    // preemption can only ever inflate a sample, never deflate it, so the
    // minimum is the closest observable estimate of true compute cost.
    await POST(postRequest(scenarioBody));

    let elapsedMs = Infinity;
    let response!: Response;
    for (let i = 0; i < 3; i += 1) {
      const start = performance.now();
      response = await POST(postRequest(scenarioBody));
      elapsedMs = Math.min(elapsedMs, performance.now() - start);
    }

    expect(response.status).toBe(200);
    const body = await response.json();

    // Round-trip budget: engine is ~10ms warm; 1s is the generous ceiling that
    // still catches an algorithmic regression (e.g. an accidental O(plans^2)).
    expect(elapsedMs).toBeLessThan(1000);

    expect(body.changed_plan_keys).toEqual([largestPlan.plan_key]);
    expect(body.affected).toHaveLength(1);

    const before = body.baseline.shares[largestPlan.plan_key];
    const after = body.scenario.shares[largestPlan.plan_key];
    expect(typeof before).toBe("number");
    expect(typeof after).toBe("number");

    // A cheaper premium is a net positive utility change (delta_u = b_premium
    // * (-15/10) = +1.85 under this pilot's fitted coefficients); dropping
    // dental is a net negative one (delta_u = -b_dental = -2.61). The dental
    // loss is the larger of the two swings, so the combined change is net
    // negative and share should fall. If this ever flips, it's a real
    // signal the fitted coefficients (or this plan) changed enough to
    // change the story -- worth eyeballing, not silently loosening this.
    expect(after).toBeLessThan(before);

    // Monte Carlo bounds bracket the scenario point estimate for the
    // changed plan (p10 <= point <= p90), and are internally ordered.
    const band = body.scenario.bounds[largestPlan.plan_key];
    expect(band.p10).toBeLessThanOrEqual(band.p50);
    expect(band.p50).toBeLessThanOrEqual(band.p90);
    expect(after).toBeGreaterThanOrEqual(band.p10);
    expect(after).toBeLessThanOrEqual(band.p90);

    // top_movers never includes the plan that was directly changed.
    expect(body.top_movers.some((m: { plan_key: string }) => m.plan_key === largestPlan.plan_key)).toBe(false);
    expect(body.top_movers.length).toBeGreaterThan(0);
  });

  it("rejects a request with no changes (400)", async () => {
    const response = await POST(postRequest({ changes: [] }));
    expect(response.status).toBe(400);
  });

  it("rejects a change with both delta and set (400)", async () => {
    const response = await POST(
      postRequest({ changes: [{ plan_key: largestPlan.plan_key, field: "premium_total", delta: -5, set: 10 }] }),
    );
    expect(response.status).toBe(400);
  });

  it("rejects a boolean field given a delta instead of set (400)", async () => {
    const response = await POST(
      postRequest({ changes: [{ plan_key: largestPlan.plan_key, field: "has_vision", delta: 1 }] }),
    );
    expect(response.status).toBe(400);
  });

  it("rejects an unknown plan_key (400)", async () => {
    const response = await POST(
      postRequest({ changes: [{ plan_key: "NOT-A-REAL-PLAN", field: "premium_total", delta: -5 }] }),
    );
    expect(response.status).toBe(400);
  });

  it("rejects malformed JSON (400)", async () => {
    const response = await POST(
      new Request("http://localhost/api/scenario", { method: "POST", body: "{not json" }),
    );
    expect(response.status).toBe(400);
  });

  it("documents an honest limitation: star_rating changes have NO effect on share, because b_star was fit to 0", async () => {
    // Guards against a silent regression: if a future recalibration ever
    // fits a nonzero b_star, this test should start failing loudly (not
    // stay green while the methodology sidebar's "b_star fit to 0" copy
    // goes stale) -- see the methodology section for the honest writeup.
    const response = await POST(
      postRequest({ changes: [{ plan_key: largestPlan.plan_key, field: "star_rating", delta: 1 }] }),
    );
    const body = await response.json();
    expect(body.scenario.shares[largestPlan.plan_key]).toBeCloseTo(body.baseline.shares[largestPlan.plan_key], 9);
  });
});
