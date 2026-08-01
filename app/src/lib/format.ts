/**
 * Shared number/string formatting helpers for the report + scenario UI.
 * Pure functions -- no locale/env dependence beyond the fixed "en-US" used
 * throughout (a public leadership-pitch demo, single audience/locale).
 */

/** A fractional share (0..1) -> signed percentage-point string, e.g.
 * 0.01235 -> "+1.24pp", -0.00419 -> "-0.42pp". `digits` controls decimal
 * places (default 2). */
export function formatPP(shareDelta: number, digits = 2): string {
  return formatSignedPP(shareDelta * 100, digits);
}

/** A value ALREADY IN percentage-point units (not a 0..1 fraction) ->
 * signed pp string, e.g. 1.235 -> "+1.24pp", -0.419 -> "-0.42pp". Use this
 * (not `formatPP`) for values already computed as `(after - before) * 100`,
 * e.g. `ShareShiftRow.predictedPP` or the scenario API's `delta_pp`. */
export function formatSignedPP(ppValue: number, digits = 2): string {
  const rounded = ppValue.toFixed(digits);
  if (ppValue > 0) return `+${rounded}pp`;
  return `${rounded}pp`;
}

/** A fractional MAGNITUDE (0..1, e.g. an error term -- never signed) ->
 * unsigned percentage-point string, e.g. 0.012348 -> "1.23pp". */
export function formatAbsPP(magnitude: number, digits = 2): string {
  return `${(magnitude * 100).toFixed(digits)}pp`;
}

/** A fractional share (0..1) -> plain percentage string, e.g. 0.418 -> "41.8%". */
export function formatPercent(share: number | null | undefined, digits = 1): string {
  if (share === null || share === undefined || Number.isNaN(share)) return "—";
  return `${(share * 100).toFixed(digits)}%`;
}

/** Dollar amount -> "$12.03" / "$0". */
export function formatMoney(amount: number, digits = 2): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(amount);
}

/** Signed dollar delta -> "+$15.00" / "-$5.00" / "$0.00". */
export function formatMoneyDelta(amount: number, digits = 2): string {
  const formatted = formatMoney(Math.abs(amount), digits);
  if (amount > 0) return `+${formatted}`;
  if (amount < 0) return `-${formatted}`;
  return formatted;
}

/** Integer people count -> "19,688" (or "771,696" etc). */
export function formatCount(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(Math.round(value));
}

/** Compact large numbers -> "19.7K" / "1.2M". Used where space is tight. */
export function formatCompact(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

/** Star rating -> "4.0 stars" / "3.5 stars" / "Not yet rated" for null. */
export function formatStars(rating: number | null | undefined): string {
  if (rating === null || rating === undefined) return "Not yet rated";
  return `${rating.toFixed(1)} stars`;
}

/** Title-cases an underscore_or-hyphen token, e.g. "price_sensitive" -> "Price sensitive". */
export function humanizeToken(token: string): string {
  const spaced = token.replace(/[_-]+/g, " ").trim();
  if (spaced.length === 0) return spaced;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Age band label passthrough (already human: "65-69", "85+"). */
export function formatAgeBand(ageBand: string): string {
  return ageBand === "85+" ? "85+" : `${ageBand} years`;
}

/** Org + plan name -> a display label, without duplicating the org name
 * when `plan_name` already starts with it (case-insensitively) -- e.g.
 * org="Humana", plan_name="Humana Gold Plus H0028-023 (HMO)" -> just the
 * plan name, not "Humana Humana Gold Plus...". ~41% of real plans in this
 * market already lead with their org name. Falls back to concatenation
 * otherwise (e.g. org="UnitedHealthcare", plan_name="AARP Medicare
 * Advantage..."). Shared by every UI surface that renders a plan label
 * (persona cards, scenario picker/tables) so the rule lives in one place. */
export function planLabel(orgName: string, planName: string): string {
  const trimmedPlan = planName.trim();
  const trimmedOrg = orgName.trim();
  if (trimmedOrg.length > 0 && trimmedPlan.toLowerCase().startsWith(trimmedOrg.toLowerCase())) {
    return trimmedPlan;
  }
  return `${trimmedOrg} ${trimmedPlan}`.trim();
}
