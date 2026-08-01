import { describe, expect, it } from "vitest";

import {
  formatAbsPP,
  formatAgeBand,
  formatCompact,
  formatCount,
  formatMoney,
  formatMoneyDelta,
  formatPP,
  formatPercent,
  formatSignedPP,
  formatStars,
  humanizeToken,
  planLabel,
} from "@/lib/format";

describe("formatPP (fraction input)", () => {
  it("formats a positive share delta with a leading plus", () => {
    expect(formatPP(0.0125)).toBe("+1.25pp");
  });
  it("formats a negative share delta with a leading minus, no double sign", () => {
    expect(formatPP(-0.00419)).toBe("-0.42pp");
  });
  it("formats exactly zero with no sign", () => {
    expect(formatPP(0)).toBe("0.00pp");
  });
});

describe("formatSignedPP (already-in-pp-units input)", () => {
  it("adds a leading plus for positive values", () => {
    expect(formatSignedPP(1.235)).toBe("+1.24pp");
  });
  it("keeps the native minus for negative values", () => {
    expect(formatSignedPP(-1.9518039483838845, 3)).toBe("-1.952pp");
  });
});

describe("formatAbsPP", () => {
  it("never signs a magnitude, even though the underlying number could be interpreted as signed", () => {
    expect(formatAbsPP(0.012347926074570302)).toBe("1.23pp");
    expect(formatAbsPP(0.004186456355069875)).toBe("0.42pp");
  });
});

describe("formatPercent", () => {
  it("formats a fraction as a percentage", () => {
    expect(formatPercent(0.7142857142857143)).toBe("71.4%");
  });
  it("renders an em dash for null/undefined", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(undefined)).toBe("—");
  });
});

describe("formatMoney / formatMoneyDelta", () => {
  it("formats a plain dollar amount", () => {
    expect(formatMoney(17)).toBe("$17.00");
    expect(formatMoney(6700, 0)).toBe("$6,700");
  });
  it("signs a delta", () => {
    expect(formatMoneyDelta(-15, 0)).toBe("-$15");
    expect(formatMoneyDelta(15, 0)).toBe("+$15");
    expect(formatMoneyDelta(0, 0)).toBe("$0");
  });
});

describe("formatCount / formatCompact", () => {
  it("comma-formats an integer count", () => {
    expect(formatCount(19688.007588)).toBe("19,688");
    expect(formatCount(771696)).toBe("771,696");
  });
  it("compacts large numbers", () => {
    expect(formatCompact(19688)).toBe("19.7K");
  });
});

describe("formatStars", () => {
  it("formats a rating to one decimal", () => {
    expect(formatStars(3.5)).toBe("3.5 stars");
  });
  it("handles a missing rating", () => {
    expect(formatStars(null)).toBe("Not yet rated");
    expect(formatStars(undefined)).toBe("Not yet rated");
  });
});

describe("humanizeToken / formatAgeBand", () => {
  it("title-cases underscore tokens", () => {
    expect(humanizeToken("price_sensitive")).toBe("Price sensitive");
    expect(humanizeToken("brand_loyal")).toBe("Brand loyal");
  });
  it("leaves 85+ as-is but appends 'years' to a range", () => {
    expect(formatAgeBand("85+")).toBe("85+");
    expect(formatAgeBand("65-69")).toBe("65-69 years");
  });
});

describe("planLabel", () => {
  it("drops the org prefix when plan_name already starts with it (Humana pattern)", () => {
    expect(planLabel("Humana", "Humana Gold Plus H0028-023 (HMO)")).toBe("Humana Gold Plus H0028-023 (HMO)");
  });

  it("keeps the org when plan_name does not start with it (UHC/AARP pattern)", () => {
    expect(planLabel("UnitedHealthcare", "AARP Medicare Advantage Choice (PPO)")).toBe(
      "UnitedHealthcare AARP Medicare Advantage Choice (PPO)",
    );
  });

  it("is case-insensitive and trims whitespace", () => {
    expect(planLabel(" humana ", "Humana Value Plus")).toBe("Humana Value Plus");
  });

  it("handles empty org", () => {
    expect(planLabel("", "Some Plan")).toBe("Some Plan");
  });
});
