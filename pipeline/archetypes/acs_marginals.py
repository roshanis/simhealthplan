"""ACS 5-year marginals for the Maricopa County 65+ population.

Derives three independent one-way marginal distributions over the
demographic axes used by the archetype IPF cube (see ``cells.py``):

  * age_band_shares    -- B01001 (sex by age), 65+ bins collapsed to
                           ``constants.AGE_BANDS``.
  * race_eth_shares     -- B03002 (Hispanic/Latino origin by race), collapsed
                           to ``constants.RACE_ETH_GROUPS``. B03002 in the
                           Phase 1 extract is county-wide (all ages), not
                           65+-specific -- there is no age x race cross-tab
                           available, so we use the county-wide race/ethnicity
                           shape as a proxy for the 65+ population. This is a
                           deliberate, documented conditional-independence
                           assumption (age ⟂ race | Maricopa County), consistent
                           with the IPF's independence assumption in cells.py.
  * income_tier_shares  -- B19037 (householder age x household income),
                           65+ row, collapsed to ``constants.INCOME_TIERS``
                           via a cutoff-selection algorithm anchored to the
                           C17002 (income-to-poverty ratio) <150% FPL share.
                           B19037 counts *households*, not persons -- another
                           documented proxy (household income tier standing
                           in for the senior householder's income tier;
                           multi-person-household effects are not modeled).

All three marginals are shares (sum to 1.0) over disjoint, exhaustive
category sets, ready to feed into ``ipf.ipf_fit`` as one-way constraints.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from archetypes.constants import AGE_BANDS, INCOME_TIERS, RACE_ETH_GROUPS

# --- B01001: sex by age -> 65+ age bands --------------------------------
# Each ACS 5-year single/paired-year bin, tagged with the AGE_BANDS bucket
# it rolls up into. Both sexes' matching bins are summed together (age band
# marginals are sex-agnostic; sex isn't one of our archetype axes).
_B01001_AGE_BAND_CODES: dict[str, list[str]] = {
    "65-69": ["B01001_020", "B01001_021", "B01001_044", "B01001_045"],
    "70-74": ["B01001_022", "B01001_046"],
    "75-84": ["B01001_023", "B01001_024", "B01001_047", "B01001_048"],
    "85+": ["B01001_025", "B01001_049"],
}

# --- B03002: Hispanic/Latino origin by race -> 5 groups -----------------
_B03002_WHITE_NH = "B03002_003"
_B03002_BLACK_NH = "B03002_004"
_B03002_ASIAN_NH = "B03002_006"
_B03002_HISPANIC = "B03002_012"
# Not-Hispanic AIAN alone, NHPI alone, some-other-race alone, and
# two-or-more-races -- everyone not-Hispanic and not White/Black/Asian alone.
_B03002_OTHER_MULTI_NH = ["B03002_005", "B03002_007", "B03002_008", "B03002_009"]

# --- C17002: ratio of income to poverty threshold (all ages) ------------
_C17002_TOTAL = "C17002_001"
_C17002_LT_150_FPL = ["C17002_002", "C17002_003", "C17002_004", "C17002_005"]

# --- B19037: householder age by household income -> 65+ row -------------
# (variable_code, lower_bound_dollars) in ascending income order.
_B19037_65PLUS_BINS: list[tuple[str, int]] = [
    ("B19037_054", 0),
    ("B19037_055", 10_000),
    ("B19037_056", 15_000),
    ("B19037_057", 20_000),
    ("B19037_058", 25_000),
    ("B19037_059", 30_000),
    ("B19037_060", 35_000),
    ("B19037_061", 40_000),
    ("B19037_062", 45_000),
    ("B19037_063", 50_000),
    ("B19037_064", 60_000),
    ("B19037_065", 75_000),
    ("B19037_066", 100_000),
    ("B19037_067", 125_000),
    ("B19037_068", 150_000),
    ("B19037_069", 200_000),
]


def _estimate(df: pd.DataFrame, variable_code: str) -> float:
    matches = df.loc[df["variable_code"] == variable_code, "estimate"]
    if matches.empty:
        raise KeyError(f"ACS variable_code {variable_code!r} not found in input DataFrame")
    return float(matches.iloc[0])


def _sum_estimates(df: pd.DataFrame, codes: list[str]) -> float:
    return sum(_estimate(df, code) for code in codes)


def age_band_shares(acs_df: pd.DataFrame) -> dict[str, float]:
    """B01001 65+ age bands (both sexes), normalized to sum to 1.0."""
    counts = {band: _sum_estimates(acs_df, codes) for band, codes in _B01001_AGE_BAND_CODES.items()}
    total = sum(counts.values())
    return {band: counts[band] / total for band in AGE_BANDS}


def race_eth_shares(acs_df: pd.DataFrame) -> dict[str, float]:
    """B03002 race/ethnicity groups (county-wide), normalized to sum to 1.0."""
    counts = {
        "white_nh": _estimate(acs_df, _B03002_WHITE_NH),
        "hispanic": _estimate(acs_df, _B03002_HISPANIC),
        "black_nh": _estimate(acs_df, _B03002_BLACK_NH),
        "asian_nh": _estimate(acs_df, _B03002_ASIAN_NH),
        "other_multi_nh": _sum_estimates(acs_df, _B03002_OTHER_MULTI_NH),
    }
    total = sum(counts.values())
    return {group: counts[group] / total for group in RACE_ETH_GROUPS}


def income_tier_shares(acs_df: pd.DataFrame) -> tuple[dict[str, float], dict]:
    """B19037 65+ householder income, collapsed to 3 tiers.

    Method (documented mapping from the task spec):
      1. Compute the county-wide <150% FPL share from C17002 -- this is the
         target share for the ``low_dual_proxy`` tier (a proxy for
         low-income/dual-eligible seniors; MCBS/CMS both treat <150% FPL as
         the LIS/dual-eligibility-adjacent threshold).
      2. Walk the B19037 65+ income bins (ascending) and pick the cutoff
         (number of bins in the low tier) whose cumulative share is closest
         to that FPL target. This is the ``low_dual_proxy`` tier.
      3. Split the remaining bins at the cutoff closest to their own
         midpoint (by cumulative share) into ``middle`` and ``higher``.

    Returns (shares, metadata) where metadata documents the chosen dollar
    cutoffs and the FPL target/achieved shares, for the archetypes.json
    metadata block.
    """
    bin_counts = [_estimate(acs_df, code) for code, _ in _B19037_65PLUS_BINS]
    total = sum(bin_counts)

    fpl_total = _estimate(acs_df, _C17002_TOTAL)
    fpl_lt_150 = _sum_estimates(acs_df, _C17002_LT_150_FPL)
    target_share = fpl_lt_150 / fpl_total

    cum = 0.0
    cum_by_k: list[float] = []
    for count in bin_counts:
        cum += count
        cum_by_k.append(cum)

    # Choose k in [1, len(bins)-1] (leave >=1 bin for middle/higher) with
    # cumulative share closest to the FPL target.
    best_k, best_diff = 1, float("inf")
    for k in range(1, len(bin_counts)):
        share = cum_by_k[k - 1] / total
        diff = abs(share - target_share)
        if diff < best_diff:
            best_k, best_diff = k, diff

    low_count = cum_by_k[best_k - 1]
    low_share = low_count / total
    low_cutoff_dollars = _B19037_65PLUS_BINS[best_k][1]  # lower bound of first excluded bin

    remaining_bins = bin_counts[best_k:]
    remaining_codes = _B19037_65PLUS_BINS[best_k:]
    remaining_total = total - low_count
    half_remaining = remaining_total / 2.0

    rem_cum = 0.0
    rem_cum_by_j: list[float] = []
    for count in remaining_bins:
        rem_cum += count
        rem_cum_by_j.append(rem_cum)

    best_j, best_j_diff = 1, float("inf")
    for j in range(1, len(remaining_bins)):
        diff = abs(rem_cum_by_j[j - 1] - half_remaining)
        if diff < best_j_diff:
            best_j, best_j_diff = j, diff
    # allow j == len(remaining_bins) - 1 at most (leave >=1 bin for "higher")
    if best_j >= len(remaining_bins):
        best_j = len(remaining_bins) - 1

    middle_count = rem_cum_by_j[best_j - 1]
    middle_share = middle_count / total
    higher_share = 1.0 - low_share - middle_share
    middle_cutoff_dollars = remaining_codes[best_j][1]

    shares = {
        "low_dual_proxy": low_share,
        "middle": middle_share,
        "higher": higher_share,
    }
    metadata = {
        "method": (
            "B19037 65+ householder income bins collapsed to 3 tiers; the "
            "low_dual_proxy cutoff is the cumulative-share bin boundary "
            "closest to the C17002 county-wide <150% FPL share, and the "
            "middle/higher split is the bin boundary closest to the median "
            "of the remaining (non-low) households."
        ),
        "target_share_lt_150_fpl": target_share,
        "low_dual_proxy_cutoff_dollars": low_cutoff_dollars,
        "low_dual_proxy_achieved_share": low_share,
        "middle_cutoff_dollars": middle_cutoff_dollars,
    }
    return shares, metadata


@dataclass(frozen=True)
class ACSMarginals:
    age_band_shares: dict[str, float]
    race_eth_shares: dict[str, float]
    income_tier_shares: dict[str, float]
    income_tier_metadata: dict


def build_marginals(acs_df: pd.DataFrame) -> ACSMarginals:
    """Compute all three ACS marginals from the tidy acs_maricopa.parquet frame."""
    income_shares, income_meta = income_tier_shares(acs_df)
    return ACSMarginals(
        age_band_shares=age_band_shares(acs_df),
        race_eth_shares=race_eth_shares(acs_df),
        income_tier_shares=income_shares,
        income_tier_metadata=income_meta,
    )
