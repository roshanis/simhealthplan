"""Choice-set eligibility rules for the Phase 3 multinomial-logit choice model.

Hard filters, applied consistently to BOTH (a) the softmax choice set
`utility.choice_probabilities` is evaluated over, and (b) renormalization of
Phase 2's ``prior_plan_year1`` mass (``renormalize_prior_plan``), so
aggregate Year-1 shares stay internally consistent with the restricted
choice sets used for calibration.

Three rules, each keyed off a plan's ``snp_type``:

  * D-SNP (``snp_type == "Dual-Eligible"``): a REAL CMS eligibility rule
    (not a proxy) -- restricted to archetypes with ``dual_proxy == True``.
    This was already hard-enforced in Phase 2's IPF seed (see
    ``archetypes/plan_priors.py``); prior_plan_year1 already holds exactly
    zero D-SNP mass for non-dual archetypes.
  * I-SNP (``snp_type == "Institutional"``): true CMS eligibility requires
    residence in a long-term-care institution (or an equivalent level-of-
    need determination), which this pipeline's archetype data cannot
    observe. EXPLICIT PROXY: restricted to ``age_band == "85+"`` archetypes,
    on the assumption that institutionalization risk concentrates in the
    oldest-old. This is an approximation, not a CMS rule, and is documented
    here and in ``CHOICE_SET_RULES``/coefficients.json metadata so it isn't
    mistaken for ground truth.
  * C-SNP (``snp_type == "Chronic or Disabling Condition"``): true CMS
    eligibility requires a qualifying chronic-condition diagnosis,
    unobserved here. EXPLICIT PROXY: restricted to
    ``attitude_segment == "health_status_driven"`` archetypes, on the
    assumption that MCBS-derived health-status-driven attitudes correlate
    with having a qualifying chronic condition. Also an approximation, not
    a CMS rule.

Any other ``snp_type`` (i.e. "Not Applicable") is eligible for every
archetype.

Because I-SNP/C-SNP restrictions were NOT enforced in Phase 2's IPF fit
(only D-SNP was), an archetype's ``prior_plan_year1`` may hold nonzero mass
on an I-SNP/C-SNP plan this module now excludes for it.
``renormalize_prior_plan`` zeroes that ineligible mass and renormalizes the
remainder across the archetype's eligible set (including the always-
eligible outside option) so the distribution still sums to 1.
"""

from __future__ import annotations

DUAL_SNP_TYPE = "Dual-Eligible"
INSTITUTIONAL_SNP_TYPE = "Institutional"
CHRONIC_SNP_TYPE = "Chronic or Disabling Condition"
NOT_APPLICABLE_SNP_TYPE = "Not Applicable"

INSTITUTIONAL_AGE_BAND = "85+"
CHRONIC_SEGMENT = "health_status_driven"

# Flat, language-neutral rule table -- also embedded (verbatim) into
# coefficients.json's choice_set_rules for the TS port / documentation.
CHOICE_SET_RULES: dict[str, dict] = {
    "dsnp": {
        "snp_type": DUAL_SNP_TYPE,
        "eligibility_field": "dual_proxy",
        "eligibility_value": True,
        "proxy": False,
        "note": "Real CMS D-SNP eligibility rule; dual_proxy is Phase 2's ACS/CMS-income-derived proxy for dual eligibility.",
    },
    "isnp": {
        "snp_type": INSTITUTIONAL_SNP_TYPE,
        "eligibility_field": "age_band",
        "eligibility_value": INSTITUTIONAL_AGE_BAND,
        "proxy": True,
        "note": "Explicit proxy: true I-SNP eligibility requires institutional/long-term-care residence, unobserved here; approximated by age_band == '85+'.",
    },
    "csnp": {
        "snp_type": CHRONIC_SNP_TYPE,
        "eligibility_field": "attitude_segment",
        "eligibility_value": CHRONIC_SEGMENT,
        "proxy": True,
        "note": "Explicit proxy: true C-SNP eligibility requires a qualifying chronic-condition diagnosis, unobserved here; approximated by attitude_segment == 'health_status_driven'.",
    },
}


def is_eligible(archetype: dict, plan: dict) -> bool:
    """Whether `archetype` may enroll in `plan` under the Phase 3 hard filters."""
    snp_type = plan.get("snp_type", NOT_APPLICABLE_SNP_TYPE)
    if snp_type == DUAL_SNP_TYPE:
        return bool(archetype.get("dual_proxy", False))
    if snp_type == INSTITUTIONAL_SNP_TYPE:
        return archetype.get("age_band") == INSTITUTIONAL_AGE_BAND
    if snp_type == CHRONIC_SNP_TYPE:
        return archetype.get("attitude_segment") == CHRONIC_SEGMENT
    return True


def eligible_plan_keys(archetype: dict, plans: list[dict]) -> list[str]:
    """plan_key list for `plans` this archetype is eligible for, in input order."""
    return [plan["plan_key"] for plan in plans if is_eligible(archetype, plan)]


def eligible_plans(archetype: dict, plans: list[dict]) -> list[dict]:
    """Sublist of `plans` this archetype is eligible for, in input order."""
    return [plan for plan in plans if is_eligible(archetype, plan)]


def renormalize_prior_plan(
    prior_plan_year1: dict[str, float],
    archetype: dict,
    plans: list[dict],
    outside_key: str,
) -> dict[str, float]:
    """Zero ineligible-plan prior mass and renormalize the remainder to sum to 1.

    `prior_plan_year1` maps plan_key/outside_key -> Year-1 prior
    probability (e.g. an archetype's Phase 2 `prior_plan_year1`). The
    outside option (`outside_key`) is always treated as eligible. Any key in
    `prior_plan_year1` that isn't `outside_key` and isn't found in `plans`
    is treated conservatively as ineligible (excluded) -- this shouldn't
    happen for a 2024 prior evaluated against the full 2024 plan universe,
    but avoids silently keeping mass on an unknown plan otherwise.

    Degenerate case (no eligible mass at all, which shouldn't occur since
    the outside option is always eligible): falls back to probability 1.0
    on the outside option.
    """
    plan_by_key = {plan["plan_key"]: plan for plan in plans}

    eligible_keys: set[str] = set()
    for key in prior_plan_year1:
        if key == outside_key:
            eligible_keys.add(key)
            continue
        plan = plan_by_key.get(key)
        if plan is not None and is_eligible(archetype, plan):
            eligible_keys.add(key)

    total_eligible_mass = sum(value for key, value in prior_plan_year1.items() if key in eligible_keys)

    if total_eligible_mass <= 0:
        return {key: (1.0 if key == outside_key else 0.0) for key in prior_plan_year1}

    return {
        key: (value / total_eligible_mass if key in eligible_keys else 0.0) for key, value in prior_plan_year1.items()
    }
