/**
 * Focused coverage for `planLabel` (shared org+plan display-label helper,
 * lives in `lib/format.ts` and is used by all 4 call sites that render a
 * plan label: `lib/report/personas.ts` and 3 spots in
 * `components/scenario/ScenarioDemo.tsx`). Broader formatting coverage for
 * the rest of `lib/format.ts` lives in `tests/lib/format.test.ts`; this
 * file exists specifically so the org-name-duplication bug class
 * (`agents-build-log.md`'s 2026-08-01T05:45Z review) has its own
 * regression home, including real org/plan_name pairs pulled from
 * `app/src/data/market.json` rather than only synthetic fixtures.
 */
import { describe, expect, it } from "vitest";

import { planLabel } from "@/lib/format";

describe("planLabel", () => {
  it("returns plan_name as-is on an exact prefix match (org_name === leading substring)", () => {
    expect(planLabel("Humana", "Humana Gold Plus H0028-023 (HMO)")).toBe("Humana Gold Plus H0028-023 (HMO)");
  });

  it("matches case-insensitively", () => {
    expect(planLabel("HUMANA", "humana value plus (hmo)")).toBe("humana value plus (hmo)");
    expect(planLabel("humana", "Humana Gold Plus H0028-023 (HMO)")).toBe("Humana Gold Plus H0028-023 (HMO)");
  });

  it("falls back to concatenation when plan_name does not start with org_name", () => {
    expect(planLabel("UnitedHealthcare", "AARP Medicare Advantage Choice (PPO)")).toBe(
      "UnitedHealthcare AARP Medicare Advantage Choice (PPO)",
    );
  });

  it("treats an empty org_name as a no-op prefix (returns plan_name alone, no leading space)", () => {
    expect(planLabel("", "Some Plan (HMO)")).toBe("Some Plan (HMO)");
  });

  it("treats a whitespace-only org_name the same as empty (trimmed before comparing/concatenating)", () => {
    expect(planLabel("   ", "Some Plan (HMO)")).toBe("Some Plan (HMO)");
  });

  it("trims incidental surrounding whitespace on both inputs before comparing", () => {
    expect(planLabel("  Humana  ", "  Humana Gold Plus H0028-023 (HMO)  ")).toBe("Humana Gold Plus H0028-023 (HMO)");
  });

  // Real org/plan_name pairs read from app/src/data/market.json's 2025
  // plan roster -- one prefix-duplication case, one non-duplication case.
  it("de-duplicates a real prefixed pair from market.json (Humana)", () => {
    expect(planLabel("Humana", "Humana Gold Plus H0028-027 (HMO)")).toBe("Humana Gold Plus H0028-027 (HMO)");
  });

  it("concatenates a real non-prefixed pair from market.json (AZ Blue)", () => {
    expect(planLabel("Blue Cross Blue Shield of Arizona (AZ Blue)", "Blue Best Life Plus (HMO)")).toBe(
      "Blue Cross Blue Shield of Arizona (AZ Blue) Blue Best Life Plus (HMO)",
    );
  });

  it("concatenates a real non-prefixed pair from market.json (UnitedHealthcare D-SNP)", () => {
    expect(planLabel("UnitedHealthcare", "UHC Dual Complete AZ-S001 (HMO-POS D-SNP)")).toBe(
      "UnitedHealthcare UHC Dual Complete AZ-S001 (HMO-POS D-SNP)",
    );
  });
});
