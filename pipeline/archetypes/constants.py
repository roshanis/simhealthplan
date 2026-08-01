"""Shared category orderings for Phase 2 archetype generation.

Every module in this package iterates demographic/attitude categories in
these fixed orders so that array axes line up (IPF cells, JSON output) and
reruns are byte-identical (no dependence on dict/set iteration order).
"""

from __future__ import annotations

# ACS-derived age bands for the Maricopa 65+ population (B01001).
AGE_BANDS: list[str] = ["65-69", "70-74", "75-84", "85+"]

# ACS-derived senior income tiers (B19037 65+ householder income,
# cutoffs anchored to the C17002 <150% FPL share -- see acs_marginals.py).
INCOME_TIERS: list[str] = ["low_dual_proxy", "middle", "higher"]

# ACS-derived race/ethnicity groups (B03002).
RACE_ETH_GROUPS: list[str] = ["white_nh", "hispanic", "black_nh", "asian_nh", "other_multi_nh"]

# MCBS-derived national attitude segments (see mcbs_segments.py).
ATTITUDE_SEGMENTS: list[str] = [
    "price_sensitive",
    "benefit_maximizer",
    "brand_loyal",
    "health_status_driven",
]
