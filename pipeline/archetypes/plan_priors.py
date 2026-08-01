"""Year-1 (2024) prior-plan distributions per archetype.

Builds an archetype x plan seed matrix from the 2024 competitive landscape
(``landscape_2024.parquet`` + ``benefits_2024.parquet``) and actual 2024
CPSC Maricopa enrollment (``cpsc_2024_03.parquet``), then fits it to the
real plan-level enrollment margins via doubly-constrained IPF
(``ipf.ipf_fit``): rows sum to each archetype's population weight, columns
sum to actual 2024 plan enrollment. Phase 3 will re-seed a logit-based
choice model for Year 2; this IPF-calibrated matrix is the Phase 2
deliverable ("what did each archetype plausibly do in Year 1").

Plan universe: the 93 plans in ``landscape_2024.parquet`` -- the county's
actual competitive landscape, which the rest of this pipeline treats as
"the market". CPSC enrollment also includes ~2,150 other contract/plan
combos with a handful of Maricopa residents each (legacy/closed plans,
national plans not marketed here, etc.) that carry no landscape attributes
(premium, SNP type, benefits) to seed a plausibility-based prior with. Both
that residual AND beneficiaries not enrolled in any MA plan (eligibles who
are in traditional Medicare, etc.) are combined into one outside option,
``OUTSIDE_PLAN_KEY``, so every archetype's prior_plan_year1 distribution is
a full probability distribution over {93 landscape plans, outside} summing
to 1. This residual is NOT decomposable further with the available data and
should not be read as "not enrolled in MA" alone.

Hard constraint: SNP type "Dual-Eligible" (D-SNP) plans get a zero seed for
every archetype whose ``dual_proxy`` is False. Multiplicative IPF preserves
exact zeros, so this holds after fitting too (see ipf.py docstring).

Mild plausibility tilts (documented, applied to the seed *before* IPF, so
IPF's margin-fitting redistributes mass around them rather than overriding
them):
  * price_sensitive archetypes get a seed boost on $0-Part-C-premium plans.
  * benefit_maximizer archetypes get a seed boost scaling with a plan's
    supplemental-benefit richness (dental/vision/hearing/OTC-flex count,
    0-4, from benefits_2024.parquet).
No tilt is applied for brand_loyal, health_status_driven, or "mixed"
(Other-catch-all) archetypes -- the spec calls out only these two tilts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from archetypes.ipf import ipf_fit

OUTSIDE_PLAN_KEY = "other_or_no_ma_2024"
DSNP_SNP_TYPE_VALUE = "Dual-Eligible"
DEFAULT_SUPPRESSED_ENROLLMENT_IMPUTE = 5

# Seed tilt strengths ("mild" per spec): price_sensitive archetypes get a
# 50% seed boost on $0-premium plans; benefit_maximizer archetypes get up to
# a 50% seed boost, scaling linearly with rich_benefit_count / 4.
PRICE_TILT_ZERO_PREMIUM = 1.5
BENEFIT_TILT_MAX = 0.5

_RICH_BENEFIT_COLUMNS = ["has_comprehensive_dental", "has_vision", "has_hearing_aids", "has_otc_or_flex"]


def plan_key(contract_id: str, plan_id: str) -> str:
    return f"{contract_id}-{plan_id}"


def build_plan_universe(landscape_df: pd.DataFrame, benefits_df: pd.DataFrame) -> pd.DataFrame:
    """One row per landscape plan: plan_key, is_dsnp, premium/benefit tilt attributes."""
    land = landscape_df[["contract_id", "plan_id", "snp_type", "premium_part_c"]].copy()
    land["plan_key"] = [plan_key(c, p) for c, p in zip(land["contract_id"], land["plan_id"])]
    land["is_dsnp"] = land["snp_type"] == DSNP_SNP_TYPE_VALUE
    land["is_zero_premium"] = land["premium_part_c"].fillna(0.0) == 0.0

    ben = benefits_df.copy()
    ben["plan_key"] = [plan_key(c, p) for c, p in zip(ben["contract_id"], ben["plan_id"])]
    ben["rich_benefit_count"] = ben[_RICH_BENEFIT_COLUMNS].sum(axis=1).astype(int)

    merged = land.merge(ben[["plan_key", "rich_benefit_count"]], on="plan_key", how="left")
    merged["rich_benefit_count"] = merged["rich_benefit_count"].fillna(0).astype(int)

    return (
        merged[["plan_key", "contract_id", "plan_id", "is_dsnp", "premium_part_c", "is_zero_premium", "rich_benefit_count"]]
        .sort_values("plan_key", kind="mergesort")
        .reset_index(drop=True)
    )


def cpsc_plan_targets(
    cpsc_df: pd.DataFrame,
    plan_universe: pd.DataFrame,
    eligibles_total: float,
    impute_suppressed: int = DEFAULT_SUPPRESSED_ENROLLMENT_IMPUTE,
) -> pd.Series:
    """Actual 2024 CPSC enrollment per landscape plan, plus the outside residual.

    Suppressed cells (enrollment withheld for small-cell privacy) are
    imputed to ``impute_suppressed``. Rows for contract/plan combos outside
    the landscape universe are dropped (see module docstring). Returns a
    Series indexed by plan_key (+ ``OUTSIDE_PLAN_KEY``) summing exactly to
    ``eligibles_total``.
    """
    cpsc = cpsc_df.copy()
    cpsc["plan_key"] = [plan_key(c, p) for c, p in zip(cpsc["contract_id"], cpsc["plan_id"])]

    universe_keys = list(plan_universe["plan_key"])
    sub = cpsc[cpsc["plan_key"].isin(universe_keys)].copy()

    enrollment = pd.to_numeric(sub["enrollment"], errors="coerce").to_numpy(dtype=float)
    suppressed = sub["suppressed"].astype(bool).to_numpy()
    sub["enrollment_imputed"] = np.where(suppressed, float(impute_suppressed), enrollment)

    by_plan = sub.groupby("plan_key")["enrollment_imputed"].sum()
    # Every landscape plan should appear in CPSC; fall back to 0 for any
    # that genuinely don't (distinct from the suppressed-cell imputation).
    by_plan = by_plan.reindex(universe_keys, fill_value=0.0)

    landscape_total = float(by_plan.sum())
    outside = eligibles_total - landscape_total

    result = pd.concat([by_plan, pd.Series({OUTSIDE_PLAN_KEY: outside})])
    return result.astype(float)


def build_seed_matrix(
    archetypes_df: pd.DataFrame,
    plan_universe: pd.DataFrame,
    price_tilt: float = PRICE_TILT_ZERO_PREMIUM,
    benefit_tilt_max: float = BENEFIT_TILT_MAX,
) -> pd.DataFrame:
    """Archetype x plan seed matrix with the D-SNP hard zero and mild tilts.

    ``archetypes_df`` must have columns: archetype_id, attitude_segment,
    dual_proxy. Index/columns of the result are ordered by
    ``plan_universe["plan_key"]`` then ``OUTSIDE_PLAN_KEY``.
    """
    plan_keys = list(plan_universe["plan_key"]) + [OUTSIDE_PLAN_KEY]
    universe_by_key = plan_universe.set_index("plan_key")

    seed = pd.DataFrame(
        1.0, index=archetypes_df["archetype_id"].to_list(), columns=plan_keys, dtype=float
    )

    for _, arche in archetypes_df.iterrows():
        aid = arche["archetype_id"]
        segment = arche["attitude_segment"]
        dual = bool(arche["dual_proxy"])
        for pk in universe_by_key.index:
            info = universe_by_key.loc[pk]
            if bool(info["is_dsnp"]) and not dual:
                seed.loc[aid, pk] = 0.0
                continue
            value = 1.0
            if segment == "price_sensitive" and bool(info["is_zero_premium"]):
                value *= price_tilt
            if segment == "benefit_maximizer":
                value *= 1.0 + benefit_tilt_max * (int(info["rich_benefit_count"]) / 4.0)
            seed.loc[aid, pk] = value
        # OUTSIDE_PLAN_KEY keeps its neutral seed of 1.0 for every archetype.

    return seed


def fit_plan_priors(
    archetypes_df: pd.DataFrame,
    plan_universe: pd.DataFrame,
    targets: pd.Series,
    tol: float = 1e-9,
) -> tuple[dict[str, dict[str, float]], int]:
    """Doubly-constrained IPF: rows = archetype weight, columns = plan targets.

    Returns (priors, iterations) where priors[archetype_id][plan_key] is a
    probability (each archetype's row sums to 1.0).
    """
    seed = build_seed_matrix(archetypes_df, plan_universe)
    plan_keys = list(seed.columns)
    archetype_ids = list(seed.index)

    weight_by_id = archetypes_df.set_index("archetype_id")["weight"]
    row_target = weight_by_id.loc[archetype_ids].to_numpy(dtype=float)
    col_target = targets.loc[plan_keys].to_numpy(dtype=float)

    table, iterations = ipf_fit([row_target, col_target], seed=seed.to_numpy(dtype=float), tol=tol)

    priors: dict[str, dict[str, float]] = {}
    for i, aid in enumerate(archetype_ids):
        w = row_target[i]
        if w <= 0:
            priors[aid] = dict.fromkeys(plan_keys, 0.0)
            continue
        probs = table[i, :] / w
        priors[aid] = dict(zip(plan_keys, (float(p) for p in probs)))

    return priors, iterations
