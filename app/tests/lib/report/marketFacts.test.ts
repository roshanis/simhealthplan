import { describe, expect, it } from "vitest";

import type { MarketData, MarketPlan, OrgRollup } from "@/lib/data/types";
import { buildMarketFacts } from "@/lib/report/marketFacts";

function makePlan(overrides: Partial<MarketPlan> = {}): MarketPlan {
  return {
    plan_key: "H0001-001",
    org_name: "Acme",
    plan_name: "Acme Plan",
    plan_type: "HMO",
    is_ppo: false,
    snp_type: "Not Applicable",
    premium_total: 20,
    moop_inn: 5000,
    star_rating: 4,
    has_comprehensive_dental: true,
    has_vision: true,
    has_hearing_aids: true,
    has_otc_or_flex: true,
    imputed_moop: false,
    imputed_star: false,
    enrollment: 100,
    ...overrides,
  };
}

function makeMarket(): MarketData {
  const plans2024: MarketPlan[] = [makePlan({ plan_key: "A", premium_total: 0 }), makePlan({ plan_key: "B", premium_total: 40 })];
  const plans2025: MarketPlan[] = [
    makePlan({ plan_key: "A", premium_total: 0 }),
    makePlan({ plan_key: "B", premium_total: 40 }),
    makePlan({ plan_key: "C", org_name: "Acme", premium_total: 20 }),
  ];
  const rollups2025: OrgRollup[] = [
    { org_name: "Acme", plan_count: 3, total_enrollment: 300, avg_premium: 20, avg_star_rating: 4 },
  ];
  return {
    metadata: { year1: 2024, year2: 2025, enrollment_month: 3 },
    plans: { "2024": plans2024, "2025": plans2025 },
    org_rollups: { "2024": [], "2025": rollups2025 },
    market_totals: {
      "2024": { plan_count: 2, total_ma_enrollment: 200, eligibles: 100_000, ma_penetration: 0.2 },
      "2025": { plan_count: 3, total_ma_enrollment: 300, eligibles: 110_000, ma_penetration: 0.25 },
    },
  };
}

describe("buildMarketFacts", () => {
  it("returns 4 facts", () => {
    expect(buildMarketFacts(makeMarket())).toHaveLength(4);
  });

  it("reports the plan-count delta between the two years", () => {
    const facts = buildMarketFacts(makeMarket());
    expect(facts.find((f) => f.id === "roster-size")?.text).toContain("+1 vs 2024");
    expect(facts.find((f) => f.id === "roster-size")?.text).toContain("3 Medicare Advantage plans");
  });

  it("reports eligibles growth and penetration change", () => {
    const facts = buildMarketFacts(makeMarket());
    const text = facts.find((f) => f.id === "eligibles-growth")?.text ?? "";
    expect(text).toContain("10,000");
    expect(text).toContain("20.0%");
    expect(text).toContain("25.0%");
  });

  it("names the market leader from org_rollups[year2][0]", () => {
    const facts = buildMarketFacts(makeMarket());
    expect(facts.find((f) => f.id === "market-leader")?.text).toContain("Acme leads");
  });

  it("computes the average premium and zero-premium plan share for year2", () => {
    const facts = buildMarketFacts(makeMarket());
    const text = facts.find((f) => f.id === "premium-landscape")?.text ?? "";
    // (0 + 40 + 20) / 3 = 20.00
    expect(text).toContain("$20.00");
    // 1 of 3 plans is $0 -> 33%
    expect(text).toContain("33%");
  });

  it("throws if a requested year is missing from market_totals", () => {
    const market = makeMarket();
    expect(() => buildMarketFacts(market, "2023", "2025")).toThrow();
  });
});
