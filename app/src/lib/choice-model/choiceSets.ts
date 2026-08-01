/**
 * Choice-set eligibility rules for the Phase 3 multinomial-logit choice model.
 *
 * 1:1 TypeScript port of `pipeline/choice_model/choice_sets.py` (the frozen
 * Python parity source of truth -- read that module's docstring for the
 * full rationale, including which rules are real CMS eligibility rules
 * (D-SNP) vs. explicit, documented proxies (I-SNP, C-SNP)).
 *
 * Hard filters, applied consistently to BOTH (a) the softmax choice set
 * `utility.choiceProbabilities` is evaluated over, and (b) renormalization
 * of Phase 2's `prior_plan_year1` mass (`renormalizePriorPlan`), so
 * aggregate Year-1 shares stay internally consistent with the restricted
 * choice sets used for calibration.
 *
 * Three rules, each keyed off a plan's `snp_type`:
 *
 *   - D-SNP (`snp_type === "Dual-Eligible"`): a REAL CMS eligibility rule
 *     (not a proxy) -- restricted to archetypes with `dual_proxy === true`.
 *   - I-SNP (`snp_type === "Institutional"`): EXPLICIT PROXY -- restricted
 *     to `age_band === "85+"` archetypes, on the assumption that
 *     institutionalization risk concentrates in the oldest-old. Not a CMS
 *     rule; true I-SNP eligibility requires institutional/long-term-care
 *     residence, unobserved in this pipeline's archetype data.
 *   - C-SNP (`snp_type === "Chronic or Disabling Condition"`): EXPLICIT
 *     PROXY -- restricted to `attitude_segment === "health_status_driven"`
 *     archetypes, on the assumption that MCBS-derived health-status-driven
 *     attitudes correlate with having a qualifying chronic condition. Also
 *     not a CMS rule; true C-SNP eligibility requires a qualifying
 *     chronic-condition diagnosis, unobserved here.
 *
 * Any other `snp_type` (i.e. "Not Applicable") is eligible for every
 * archetype.
 */

import type { Archetype, Plan } from "./types";

export const DUAL_SNP_TYPE = "Dual-Eligible";
export const INSTITUTIONAL_SNP_TYPE = "Institutional";
export const CHRONIC_SNP_TYPE = "Chronic or Disabling Condition";
export const NOT_APPLICABLE_SNP_TYPE = "Not Applicable";

export const INSTITUTIONAL_AGE_BAND = "85+";
export const CHRONIC_SEGMENT = "health_status_driven";

/** Flat, language-neutral rule table -- verbatim port of choice_sets.py's
 * CHOICE_SET_RULES (also embedded in coefficients.json's choice_set_rules
 * for documentation; not read from that JSON at runtime by either language). */
export const CHOICE_SET_RULES: Record<
  string,
  { snp_type: string; eligibility_field: string; eligibility_value: unknown; proxy: boolean; note: string }
> = {
  dsnp: {
    snp_type: DUAL_SNP_TYPE,
    eligibility_field: "dual_proxy",
    eligibility_value: true,
    proxy: false,
    note: "Real CMS D-SNP eligibility rule; dual_proxy is Phase 2's ACS/CMS-income-derived proxy for dual eligibility.",
  },
  isnp: {
    snp_type: INSTITUTIONAL_SNP_TYPE,
    eligibility_field: "age_band",
    eligibility_value: INSTITUTIONAL_AGE_BAND,
    proxy: true,
    note: "Explicit proxy: true I-SNP eligibility requires institutional/long-term-care residence, unobserved here; approximated by age_band == '85+'.",
  },
  csnp: {
    snp_type: CHRONIC_SNP_TYPE,
    eligibility_field: "attitude_segment",
    eligibility_value: CHRONIC_SEGMENT,
    proxy: true,
    note: "Explicit proxy: true C-SNP eligibility requires a qualifying chronic-condition diagnosis, unobserved here; approximated by attitude_segment == 'health_status_driven'.",
  },
};

/** Whether `archetype` may enroll in `plan` under the Phase 3 hard filters. */
export function isEligible(archetype: Archetype, plan: Plan): boolean {
  const snpType = plan.snp_type ?? NOT_APPLICABLE_SNP_TYPE;
  if (snpType === DUAL_SNP_TYPE) {
    return Boolean(archetype.dual_proxy);
  }
  if (snpType === INSTITUTIONAL_SNP_TYPE) {
    return archetype.age_band === INSTITUTIONAL_AGE_BAND;
  }
  if (snpType === CHRONIC_SNP_TYPE) {
    return archetype.attitude_segment === CHRONIC_SEGMENT;
  }
  return true;
}

/** plan_key list for `plans` this archetype is eligible for, in input order. */
export function eligiblePlanKeys(archetype: Archetype, plans: Plan[]): string[] {
  return plans.filter((plan) => isEligible(archetype, plan)).map((plan) => plan.plan_key);
}

/** Sublist of `plans` this archetype is eligible for, in input order. */
export function eligiblePlans(archetype: Archetype, plans: Plan[]): Plan[] {
  return plans.filter((plan) => isEligible(archetype, plan));
}

/**
 * Zero ineligible-plan prior mass and renormalize the remainder to sum to 1.
 *
 * `priorPlanYear1` maps plan_key/outsideKey -> Year-1 prior probability
 * (e.g. an archetype's Phase 2 `prior_plan_year1`). The outside option
 * (`outsideKey`) is always treated as eligible. Any key in `priorPlanYear1`
 * that isn't `outsideKey` and isn't found in `plans` is treated
 * conservatively as ineligible (excluded).
 *
 * Degenerate case (no eligible mass at all, which shouldn't occur since the
 * outside option is always eligible): falls back to probability 1.0 on the
 * outside option.
 */
export function renormalizePriorPlan(
  priorPlanYear1: Record<string, number>,
  archetype: Archetype,
  plans: Plan[],
  outsideKey: string,
): Record<string, number> {
  const planByKey = new Map(plans.map((plan) => [plan.plan_key, plan]));

  const eligibleKeys = new Set<string>();
  for (const key of Object.keys(priorPlanYear1)) {
    if (key === outsideKey) {
      eligibleKeys.add(key);
      continue;
    }
    const plan = planByKey.get(key);
    if (plan !== undefined && isEligible(archetype, plan)) {
      eligibleKeys.add(key);
    }
  }

  let totalEligibleMass = 0;
  for (const [key, value] of Object.entries(priorPlanYear1)) {
    if (eligibleKeys.has(key)) {
      totalEligibleMass += value;
    }
  }

  if (totalEligibleMass <= 0) {
    const result: Record<string, number> = {};
    for (const key of Object.keys(priorPlanYear1)) {
      result[key] = key === outsideKey ? 1.0 : 0.0;
    }
    return result;
  }

  const result: Record<string, number> = {};
  for (const [key, value] of Object.entries(priorPlanYear1)) {
    result[key] = eligibleKeys.has(key) ? value / totalEligibleMass : 0.0;
  }
  return result;
}
