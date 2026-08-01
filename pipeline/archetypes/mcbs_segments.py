"""MCBS attitude segmentation -- national, weighted, rule-based (not clustering).

Derives 4 explainable consumer segments from the MCBS Survey File PUF
(2023 Fall round, ``data/interim/mcbs_subset.parquet``):

  * price_sensitive       -- cost-driven care-seeking behavior, LIS status,
                              dissatisfaction with out-of-pocket costs.
  * benefit_maximizer     -- has/uses supplemental benefits (dental, vision,
                              hearing, nursing-home, drug coverage).
  * brand_loyal           -- satisfied with current care/plan, would
                              recommend it, stays at the same location.
  * health_status_driven  -- self-reported health, functional limitations,
                              chronic conditions.

Method (deliberately simple and explainable, NOT black-box clustering):
  1. For each segment, average a small set of documented 0-1 recoded MCBS
     variables (SEGMENT_SCORE_VARIABLES) into a raw score per respondent,
     using ``PUFFWGT``-weighted imputation for missing raw scores.
  2. Convert each of the 4 raw scores to a weighted percentile rank within
     the national respondent population (so the 4 scores, built from
     different variable mixes, are comparable).
  3. Classify each respondent into the segment on which they rank highest
     relative to their peers (row-wise argmax over the 4 percentile ranks).
     Exact ties break deterministically toward the first segment in
     ``constants.ATTITUDE_SEGMENTS`` order -- no randomness anywhere in this
     module.

MCBS is a **national** survey with no county identifier. Segment shares
here are national. Conditioning is limited to strata MCBS actually
supports: DEM_AGE (<65 / 65-74 / 75+) and DEM_INCOME (<$25k / >=$25k) --
see ``mcbs_stratum`` / ``ACS_TO_MCBS_STRATUM_AGE`` /
``ACS_TO_MCBS_STRATUM_INCOME``, which coarsen the ACS's 4 age bands and 3
income tiers onto these 4 native MCBS strata. Callers (``cells.py``) must
NOT treat these probabilities as county-specific attitude estimates -- they
are national attitude propensities conditioned on coarse age/income only.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd

from archetypes.constants import AGE_BANDS, ATTITUDE_SEGMENTS, INCOME_TIERS

WEIGHT_COLUMN = "PUFFWGT"

# --- Segment scoring variables -------------------------------------------
# Each entry: (MCBS column, {raw_code: recoded_0_to_1_value}). Higher
# recoded value always means "more of the trait". Codes not present in the
# mapping (don't know / refused / not-ascertained / no-experience / etc.)
# recode to NaN and are excluded from that respondent's average.
SEGMENT_SCORE_VARIABLES: dict[str, list[tuple[str, dict[int, float]]]] = {
    "price_sensitive": [
        # Admin LIS/premium-subsidy flag: full-year subsidy is a strong,
        # complete (no missingness) economic-hardship signal.
        ("ADM_LIS_FLAG_YR", {1: 0.0, 2: 0.5, 3: 1.0}),
        # Delayed care due to cost in the past year (yes/no).
        ("ACC_HCDELAY", {1: 1.0, 2: 0.0}),
        # Skipped/shared blood-pressure meds due to cost (yes/no).
        ("HLT_HYPESKIP", {1: 1.0, 2: 0.0}),
        # Satisfaction with out-of-pocket medical costs (dissatisfied -> price-sensitive).
        ("ACC_MCCOSTS", {1: 0.0, 2: 1 / 3, 3: 2 / 3, 4: 1.0}),
    ],
    "benefit_maximizer": [
        # Whether current coverage includes each supplemental benefit --
        # a revealed-preference proxy for valuing that benefit. INS_PRIV*
        # applies to respondents with other private insurance; MA_MADV*
        # applies to respondents enrolled in MA. The two blocks are close
        # to mutually exclusive subpopulations, so a row-wise mean over
        # all eight naturally uses whichever block applies.
        ("INS_PRIVDS", {1: 1.0, 2: 0.0}),
        ("INS_PRIVVIS", {1: 1.0, 2: 0.0}),
        ("INS_PRIVLTC", {1: 1.0, 2: 0.0}),
        ("MA_MADVDENT", {1: 1.0, 2: 0.0}),
        ("MA_MADVEYE", {1: 1.0, 2: 0.0}),
        ("MA_MADVHEAR", {1: 1.0, 2: 0.0}),
        ("MA_MADVBEH", {1: 1.0, 2: 0.0}),
        ("MA_MADVNH", {1: 1.0, 2: 0.0}),
    ],
    "brand_loyal": [
        # Would recommend their Medicare Advantage plan to family/friends.
        ("MA_RECMADV", {1: 1.0, 2: 0.0}),
        # General satisfaction items (quality, provider concern, continuity
        # of care at the same location) -- satisfied/loyal beneficiaries
        # score high here.
        ("ACC_MCQUALTY", {1: 1.0, 2: 2 / 3, 3: 1 / 3, 4: 0.0}),
        ("ACC_MCCONCRN", {1: 1.0, 2: 2 / 3, 3: 1 / 3, 4: 0.0}),
        ("ACC_MCSAMLOC", {1: 1.0, 2: 2 / 3, 3: 1 / 3, 4: 0.0}),
    ],
    "health_status_driven": [
        # Self-reported general health, higher = worse (1=excellent..5=poor).
        ("HLT_GENHELTH", {1: 0.0, 2: 0.25, 3: 0.5, 4: 0.75, 5: 1.0}),
        # Health compared to a year ago, higher = worse.
        ("HLT_COMPHLTH", {1: 0.0, 2: 0.25, 3: 0.5, 4: 0.75, 5: 1.0}),
        # Social activities limited by health, higher = more limited.
        ("HLT_HELMTACT", {1: 0.0, 2: 1 / 3, 3: 2 / 3, 4: 1.0}),
        # Functional limitations (IADLs/ADLs), higher = more limitations.
        ("HLT_FUNC_LIM", {0: 0.0, 1: 0.25, 2: 0.5, 3: 0.75, 4: 1.0}),
        # Activities limited due to a fall (yes/no).
        ("FAL_FALLIMIT", {1: 1.0, 2: 0.0}),
        # Chronic kidney disease, ever (yes/no).
        ("HLT_OCKIDNY", {1: 1.0, 2: 0.0}),
    ],
}

_SCORE_COLUMN = {segment: f"{segment}_score" for segment in ATTITUDE_SEGMENTS}
_PERCENTILE_COLUMN = {segment: f"{segment}_pctl" for segment in ATTITUDE_SEGMENTS}

# --- MCBS <-> ACS stratum mapping -----------------------------------------
# MCBS's DEM_AGE / DEM_INCOME are coarser than the ACS 4-band / 3-tier
# scheme. We compute segment shares on MCBS's native (coarser) strata, then
# broadcast each ACS (age_band, income_tier) cell onto the MCBS stratum it
# falls within. This is the documented "national conditioned on
# demographics, not county-specific" approximation.
_DEM_AGE_TO_MCBS_AGE = {2: "65_74", 3: "75_plus"}  # 1 = "<65", excluded
_DEM_INCOME_TO_MCBS_INCOME = {1: "lt25k", 2: "ge25k"}

ACS_AGE_BAND_TO_MCBS_AGE = {
    "65-69": "65_74",
    "70-74": "65_74",
    "75-84": "75_plus",
    "85+": "75_plus",
}
ACS_INCOME_TIER_TO_MCBS_INCOME = {
    "low_dual_proxy": "lt25k",
    "middle": "ge25k",
    "higher": "ge25k",
}


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _recode(series: pd.Series, mapping: dict[int, float]) -> pd.Series:
    """Coerce to numeric, then map known codes to 0-1; unknown codes -> NaN."""
    numeric = _numeric(series)
    return numeric.map(mapping)


def compute_raw_score(df: pd.DataFrame, variables: list[tuple[str, dict[int, float]]]) -> pd.Series:
    """Row-wise mean of the recoded variables, skipping missing ones."""
    recoded = pd.concat([_recode(df[col], mapping) for col, mapping in variables], axis=1)
    return recoded.mean(axis=1, skipna=True)


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna()
    return float(np.average(values[mask], weights=weights[mask]))


def compute_scores(df: pd.DataFrame, weight_col: str = WEIGHT_COLUMN) -> pd.DataFrame:
    """Add one ``<segment>_score`` column per segment, weighted-mean-imputed.

    A respondent with no non-missing indicator for a segment gets that
    segment's national PUFFWGT-weighted mean (a neutral fallback that
    lands near the middle of the eventual percentile-rank distribution).
    """
    out = df.copy()
    weights = _numeric(df[weight_col])
    for segment, variables in SEGMENT_SCORE_VARIABLES.items():
        raw = compute_raw_score(df, variables)
        imputed_mean = _weighted_mean(raw, weights)
        out[_SCORE_COLUMN[segment]] = raw.fillna(imputed_mean)
    return out


def weighted_percentile_rank(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Weighted percentile rank in (0, 1], midpoint rule for ties.

    rank(v) = (weight strictly below v + 0.5 * weight at v) / total weight.
    """
    s = pd.Series(np.asarray(weights, dtype=float), index=np.asarray(values, dtype=float))
    grp_weight = s.groupby(level=0).sum().sort_index()
    total = grp_weight.sum()
    cum = grp_weight.cumsum()
    below = cum - grp_weight  # cumulative weight strictly below this value
    rank_per_value = (below + 0.5 * grp_weight) / total
    return rank_per_value.reindex(s.index).to_numpy()


def classify_segment(df: pd.DataFrame, weight_col: str = WEIGHT_COLUMN) -> pd.Series:
    """Argmax of weighted percentile ranks across the 4 segment scores.

    Deterministic: ties break toward the earliest segment in
    ATTITUDE_SEGMENTS order (numpy.argmax returns the first max).
    """
    weights = _numeric(df[weight_col]).to_numpy()
    percentiles = np.column_stack(
        [weighted_percentile_rank(df[_SCORE_COLUMN[s]].to_numpy(), weights) for s in ATTITUDE_SEGMENTS]
    )
    idx = np.argmax(percentiles, axis=1)
    labels = np.array(ATTITUDE_SEGMENTS)[idx]
    return pd.Series(labels, index=df.index, name="attitude_segment")


def national_segment_shares(df: pd.DataFrame, weight_col: str = WEIGHT_COLUMN) -> dict[str, float]:
    weights = _numeric(df[weight_col])
    total = weights.sum()
    shares = {}
    for segment in ATTITUDE_SEGMENTS:
        mask = df["attitude_segment"] == segment
        shares[segment] = float(weights[mask].sum() / total)
    return shares


def mcbs_stratum(df: pd.DataFrame) -> pd.Series:
    """Native MCBS (age x income) stratum label, e.g. '65_74|lt25k'.

    Respondents under 65 (DEM_AGE == 1) or with an unmapped/missing code
    get None -- they're excluded from stratum-conditional segmentation
    (our archetype population is 65+ only).
    """
    age = _numeric(df["DEM_AGE"]).map(_DEM_AGE_TO_MCBS_AGE)
    income = _numeric(df["DEM_INCOME"]).map(_DEM_INCOME_TO_MCBS_INCOME)
    valid = age.notna() & income.notna()
    stratum = pd.Series([None] * len(df), index=df.index, dtype=object)
    stratum[valid] = age[valid] + "|" + income[valid]
    return stratum


def stratum_conditional_probs(df: pd.DataFrame, weight_col: str = WEIGHT_COLUMN) -> dict[str, dict[str, float]]:
    """PUFFWGT-weighted P(segment | mcbs_stratum) for each observed stratum."""
    weights = _numeric(df[weight_col])
    result: dict[str, dict[str, float]] = {}
    for stratum, group in df.groupby("mcbs_stratum"):
        if stratum is None:
            continue
        w = weights.loc[group.index]
        total = w.sum()
        result[stratum] = {
            segment: float(w[group["attitude_segment"] == segment].sum() / total) for segment in ATTITUDE_SEGMENTS
        }
    return result


def segment_probabilities_by_acs_stratum(
    mcbs_stratum_probs: dict[str, dict[str, float]],
) -> dict[tuple[str, str], dict[str, float]]:
    """Broadcast the 4 native MCBS strata onto all 12 ACS (age_band, income_tier) cells."""
    by_acs: dict[tuple[str, str], dict[str, float]] = {}
    for age_band, income_tier in product(AGE_BANDS, INCOME_TIERS):
        mcbs_age = ACS_AGE_BAND_TO_MCBS_AGE[age_band]
        mcbs_income = ACS_INCOME_TIER_TO_MCBS_INCOME[income_tier]
        stratum = f"{mcbs_age}|{mcbs_income}"
        by_acs[(age_band, income_tier)] = mcbs_stratum_probs[stratum]
    return by_acs


@dataclass(frozen=True)
class MCBSSegmentation:
    national_shares: dict[str, float]
    stratum_probabilities: dict[tuple[str, str], dict[str, float]]
    mcbs_stratum_shares: dict[str, dict[str, float]]
    n_respondents_used: int


def build_segments(mcbs_df: pd.DataFrame, weight_col: str = WEIGHT_COLUMN) -> MCBSSegmentation:
    """Full pipeline: score -> classify -> national shares -> stratum-conditional probs.

    Restricted throughout to MCBS respondents aged 65+ (DEM_AGE in {2, 3}),
    matching the archetype population's age scope.
    """
    scored = compute_scores(mcbs_df, weight_col=weight_col)
    age_numeric = _numeric(scored["DEM_AGE"])
    seniors = scored[age_numeric.isin([2, 3])].copy()

    seniors["attitude_segment"] = classify_segment(seniors, weight_col=weight_col)
    national_shares = national_segment_shares(seniors, weight_col=weight_col)

    seniors["mcbs_stratum"] = mcbs_stratum(seniors)
    stratified = seniors[seniors["mcbs_stratum"].notna()]
    mcbs_stratum_shares = stratum_conditional_probs(stratified, weight_col=weight_col)
    stratum_probabilities = segment_probabilities_by_acs_stratum(mcbs_stratum_shares)

    return MCBSSegmentation(
        national_shares=national_shares,
        stratum_probabilities=stratum_probabilities,
        mcbs_stratum_shares=mcbs_stratum_shares,
        n_respondents_used=len(seniors),
    )
