"""Demographic x attitude cell cube: build, expand, and collapse to archetypes.

Three stages, matching the Phase 2 spec:

  1. ``build_demographic_cells`` -- 4x3x5 = 60 age_band x income_tier x
     race_eth cells via 3-way IPF over the ACS marginals (``ipf.ipf_fit``
     with a uniform seed). With only one-way marginals and no cross-tab
     data, this *is* the conditional-independence assumption
     (age ⟂ income ⟂ race within the Maricopa 65+ population) -- IPF
     converges to the product-form distribution (see ``ipf.py`` docstring).
     Cells are scaled to sum to ``population_total`` (the 2024 penetration
     "eligibles" count -- the real CMS denominator for Maricopa 65+
     Medicare beneficiaries, a deliberate improvement over deriving total
     population from ACS 65+ counts, which only supply distribution shape).
  2. ``expand_with_segments`` -- 60 -> 60*4 = 240 cells, multiplying each
     demographic cell's weight by the MCBS stratum-conditional attitude
     segment probability for its (age_band, income_tier) stratum
     (``mcbs_segments.segment_probabilities_by_acs_stratum``). This assumes
     attitude segment is independent of race/ethnicity given age/income --
     documented because MCBS provides no race-conditioned segmentation at
     the granularity needed here (see mcbs_segments.py docstring).
  3. ``collapse_cells`` -- keep the highest-weight cells covering ~95% of
     cumulative population weight; fold the remaining tail into "Other"
     catch-all archetypes grouped by (age_band, income_tier) -- NOT just
     age_band -- so every catch-all still has an unambiguous dual-eligibility
     proxy status for the D-SNP hard constraint in plan_priors.py. Only
     race_eth and attitude_segment collapse to a "mixed" sentinel for these
     rows.
"""

from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from archetypes.acs_marginals import ACSMarginals
from archetypes.constants import AGE_BANDS, ATTITUDE_SEGMENTS, INCOME_TIERS, RACE_ETH_GROUPS
from archetypes.ipf import ipf_fit


def build_demographic_cells(marginals: ACSMarginals, population_total: float) -> tuple[pd.DataFrame, int]:
    """3-way IPF over (age_band, income_tier, race_eth) -> 60 weighted cells."""
    age = np.array([marginals.age_band_shares[a] for a in AGE_BANDS])
    income = np.array([marginals.income_tier_shares[i] for i in INCOME_TIERS])
    race = np.array([marginals.race_eth_shares[r] for r in RACE_ETH_GROUPS])

    table, iterations = ipf_fit([age, income, race], tol=1e-9)

    rows = []
    for (ai, a), (ii, i), (ri, r) in product(enumerate(AGE_BANDS), enumerate(INCOME_TIERS), enumerate(RACE_ETH_GROUPS)):
        rows.append(
            {
                "age_band": a,
                "income_tier": i,
                "race_eth": r,
                "weight": float(table[ai, ii, ri]) * population_total,
            }
        )
    return pd.DataFrame(rows), iterations


def expand_with_segments(
    demographic_cells: pd.DataFrame,
    stratum_probabilities: dict[tuple[str, str], dict[str, float]],
) -> pd.DataFrame:
    """Expand each demographic cell by its stratum-conditional attitude segment probabilities."""
    rows = []
    for _, cell in demographic_cells.iterrows():
        probs = stratum_probabilities[(cell["age_band"], cell["income_tier"])]
        for segment in ATTITUDE_SEGMENTS:
            rows.append(
                {
                    "age_band": cell["age_band"],
                    "income_tier": cell["income_tier"],
                    "race_eth": cell["race_eth"],
                    "attitude_segment": segment,
                    "weight": cell["weight"] * probs[segment],
                }
            )
    return pd.DataFrame(rows)


def _others_count(tail: pd.DataFrame) -> int:
    if tail.empty:
        return 0
    grp = tail.groupby(["age_band", "income_tier"])["weight"].sum()
    return int((grp > 1e-12).sum())


def collapse_cells(
    cells_df: pd.DataFrame,
    min_count: int = 30,
    max_count: int = 80,
    target_cumulative: float = 0.95,
) -> pd.DataFrame:
    """Keep top cells covering ~target_cumulative weight; fold the tail into Others.

    Guarantees: output count is clamped into [min_count, max_count] whenever
    the input has enough distinct cells to support it; every row has
    positive weight; total weight is conserved exactly.
    """
    sorted_df = cells_df.sort_values("weight", ascending=False, kind="mergesort").reset_index(drop=True)
    sorted_df = sorted_df[sorted_df["weight"] > 0].reset_index(drop=True)
    total = float(sorted_df["weight"].sum())
    n_cells = len(sorted_df)

    cum_share = np.cumsum(sorted_df["weight"].to_numpy()) / total
    n_natural = int(np.searchsorted(cum_share, target_cumulative) + 1)
    n_natural = min(n_natural, n_cells)

    def total_count(n: int) -> int:
        return n + _others_count(sorted_df.iloc[n:])

    # Shrink n if the natural cutoff overshoots max_count.
    n = n_natural
    while n > 0 and total_count(n) > max_count:
        n -= 1

    # Grow n if we're under min_count (and cells remain to promote).
    while n < n_cells and total_count(n) < min_count:
        n += 1

    top = sorted_df.iloc[:n].copy()
    top["is_other"] = False

    tail = sorted_df.iloc[n:]
    other_rows = []
    if not tail.empty:
        grouped = tail.groupby(["age_band", "income_tier"], as_index=False)["weight"].sum()
        for _, row in grouped.iterrows():
            if row["weight"] <= 0:
                continue
            other_rows.append(
                {
                    "age_band": row["age_band"],
                    "income_tier": row["income_tier"],
                    "race_eth": "mixed",
                    "attitude_segment": "mixed",
                    "weight": float(row["weight"]),
                    "is_other": True,
                }
            )
    other_df = pd.DataFrame(other_rows, columns=list(top.columns))

    result = pd.concat([top, other_df], ignore_index=True) if not other_df.empty else top
    result["dual_proxy"] = result["income_tier"] == "low_dual_proxy"
    # Stable, deterministic ordering: highest weight first, ties broken by
    # the natural category order via a fixed sort key.
    result = result.sort_values(
        by=["weight", "age_band", "income_tier", "race_eth", "attitude_segment"],
        ascending=[False, True, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    return result
