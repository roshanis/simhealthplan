"""Short, human-readable trait phrases per archetype, for later LLM persona prompts.

Deliberately built only from fields with an evidentiary basis in this
pipeline's data: attitude_segment (MCBS-derived), dual_proxy/income_tier
(ACS/CMS-derived), and age_band (ACS-derived). ``race_eth`` is intentionally
excluded from trait-phrase generation -- the MCBS segmentation provides no
race-conditioned attitude signal at this granularity (see
mcbs_segments.py), and fabricating a race-linked behavioral trait here
would not be evidence-based. Downstream persona prompts may still use the
``race_eth`` field itself for demographic realism; this module just doesn't
attach opinions to it.
"""

from __future__ import annotations

import pandas as pd

_SEGMENT_TRAITS: dict[str, list[str]] = {
    "price_sensitive": [
        "very price-conscious",
        "watches premiums and out-of-pocket costs closely",
        "willing to switch plans for meaningful savings",
    ],
    "benefit_maximizer": [
        "strongly values dental/vision/hearing extras",
        "prioritizes rich supplemental benefits and OTC/flex allowances",
    ],
    "brand_loyal": [
        "loyal to their current plan and provider relationships",
        "satisfied with current care, slow to switch",
    ],
    "health_status_driven": [
        "plan choice driven by ongoing health needs",
        "values broad provider access and care coordination",
    ],
    "mixed": [
        "attitude profile spans multiple segments (aggregated catch-all archetype)",
    ],
}

_AGE_BAND_TRAITS: dict[str, str] = {
    "65-69": "recently Medicare-eligible; still comparing plans against employer-era habits",
    "70-74": "established Medicare beneficiary with a few years of plan experience",
    "75-84": "older senior; increasing focus on health and functional needs",
    "85+": "oldest-old (85+); likely values simplicity, care coordination, and caregiver support",
}

_INCOME_TIER_TRAITS: dict[str, str] = {
    "low_dual_proxy": "income near or below 150% FPL; cost is a primary constraint",
    "middle": "middle income; balances premium cost against benefit richness",
    "higher": "financially comfortable; premium is a secondary concern",
}

_DUAL_PROXY_TRAIT = "likely dual-eligible or near-dual-eligible; highly cost-sensitive by circumstance"


def build_traits(row: pd.Series) -> list[str]:
    """Assemble 2-5 short trait phrases for one archetype row.

    ``row`` must provide: attitude_segment, age_band, income_tier,
    dual_proxy (bool). Order is deterministic (segment traits first, then
    dual-eligibility, then age, then income) and duplicates are dropped.
    """
    phrases: list[str] = []
    phrases.extend(_SEGMENT_TRAITS.get(row["attitude_segment"], []))

    if bool(row["dual_proxy"]):
        phrases.append(_DUAL_PROXY_TRAIT)

    age_trait = _AGE_BAND_TRAITS.get(row["age_band"])
    if age_trait:
        phrases.append(age_trait)

    income_trait = _INCOME_TIER_TRAITS.get(row["income_tier"])
    if income_trait and not bool(row["dual_proxy"]):
        # Avoid redundancy with _DUAL_PROXY_TRAIT for the low_dual_proxy tier.
        phrases.append(income_trait)

    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped = [p for p in phrases if not (p in seen or seen.add(p))]
    return deduped
