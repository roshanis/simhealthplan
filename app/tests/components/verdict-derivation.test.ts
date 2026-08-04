/**
 * Pure-function coverage for `VerdictSection`'s badge-derivation helpers
 * (`maeBadge`, `accuracyBadge`). These run under the default `node`
 * environment -- no DOM, no rendering -- exercising just the derivation
 * logic that turns `backtest.json`'s `summary` numbers into badge
 * status/label pairs. Rendered-output coverage for the same component
 * (asserting the text actually shows up in the DOM) lives separately in
 * `tests/components/VerdictSection.test.tsx` (jsdom).
 */
import { describe, expect, it } from "vitest";

import { accuracyBadge, maeBadge } from "@/components/report/VerdictSection";

describe("maeBadge", () => {
  it("returns the critical 'Loses to no-change' badge when beats_naive.logit is false", () => {
    expect(maeBadge(false)).toEqual({ status: "critical", label: "Loses to no-change" });
  });

  it("returns the good 'Beats no-change' badge when beats_naive.logit is true", () => {
    expect(maeBadge(true)).toEqual({ status: "good", label: "Beats no-change" });
  });

  it("returns the muted 'Pending' badge when beats_naive.logit is null", () => {
    expect(maeBadge(null)).toEqual({ status: "muted", label: "Pending" });
  });
});

describe("accuracyBadge", () => {
  it("returns 'Beats both baselines' when the model's directional accuracy beats both no_change and trend", () => {
    expect(accuracyBadge(0.714, 0.418, 0.615)).toEqual({ status: "good", label: "Beats both baselines" });
  });

  it("returns 'Beats one baseline' when the model beats only no_change", () => {
    expect(accuracyBadge(0.55, 0.5, 0.6)).toEqual({ status: "warning", label: "Beats one baseline" });
  });

  it("returns 'Beats one baseline' when the model beats only trend", () => {
    expect(accuracyBadge(0.55, 0.6, 0.5)).toEqual({ status: "warning", label: "Beats one baseline" });
  });

  it("returns 'Loses to both baselines' when the model beats neither naive baseline", () => {
    expect(accuracyBadge(0.4, 0.5, 0.6)).toEqual({ status: "critical", label: "Loses to both baselines" });
  });

  it("treats a tie as a win (>=, not >) so equal accuracy still counts as 'beats'", () => {
    expect(accuracyBadge(0.5, 0.5, 0.5)).toEqual({ status: "good", label: "Beats both baselines" });
  });
});
