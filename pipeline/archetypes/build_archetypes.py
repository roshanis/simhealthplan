"""Phase 2 entrypoint: build data/processed/archetypes.json from Phase 1 outputs.

Pipeline (see each submodule's docstring for the documented method/assumptions):
  1. acs_marginals   -- ACS 65+ age_band / income_tier / race_eth marginals.
  2. mcbs_segments    -- national MCBS attitude segments, conditioned on
                         coarse age x income strata mapped onto the ACS grid.
  3. cells            -- 3-way IPF -> 60 demographic cells, expanded by
                         attitude segment -> 240 cells, collapsed to 30-80
                         archetypes (long tail folded into "Other" catch-alls).
  4. plan_priors      -- archetype x plan seed matrix (D-SNP hard-zeroed for
                         non-dual archetypes, mild price/benefit tilts),
                         doubly-constrained IPF against actual 2024 CPSC
                         Maricopa plan enrollment.
  5. traits           -- short human-readable trait phrases per archetype.

Deterministic by construction: every step is a weighted quantile, IPF
solve, or sort over static input files -- no random sampling anywhere, so
no numpy Generator is needed for reproducibility (stronger than seeding:
identical inputs always produce identical output). ``settings.SEED`` is
still threaded into the output metadata for provenance/consistency with
later phases (e.g. Phase 3 LLM persona sampling), even though this phase
does not consume it as a random seed.

Run via ``uv run python -m archetypes.build_archetypes`` (see also
``make archetypes``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from archetypes import acs_marginals, cells, mcbs_segments, plan_priors, traits
from archetypes.constants import AGE_BANDS, INCOME_TIERS, RACE_ETH_GROUPS
from config.settings import settings

COLLAPSE_MIN_COUNT = 30
COLLAPSE_MAX_COUNT = 80
COLLAPSE_TARGET_CUMULATIVE = 0.95
IPF_TOLERANCE = 1e-9

_AGE_BAND_SLUG = {"65-69": "65_69", "70-74": "70_74", "75-84": "75_84", "85+": "85_plus"}
_INCOME_TIER_SLUG = {"low_dual_proxy": "low", "middle": "middle", "higher": "higher"}
_RACE_ETH_SLUG = {
    "white_nh": "white",
    "hispanic": "hispanic",
    "black_nh": "black",
    "asian_nh": "asian",
    "other_multi_nh": "other",
    "mixed": "mixed",
}

_ASSUMPTIONS = [
    "Demographic cells (age_band x income_tier x race_eth) assume conditional "
    "independence given ACS one-way marginals only -- no ACS cross-tabulation "
    "of all three axes for the 65+ Maricopa population was available.",
    "The race/ethnicity marginal (B03002) is county-wide (all ages), used as a "
    "proxy for the 65+ population's race/ethnicity shape; no age x race ACS "
    "cross-tab was available.",
    "income_tier is derived from B19037 65+ HOUSEHOLDER income (not "
    "person-level income); the low_dual_proxy cutoff is the B19037 bin "
    "boundary whose cumulative share is closest to the county-wide C17002 "
    "<150% FPL share (see metadata.acs_income_tier_cutoffs).",
    "Attitude segments are a national, MCBS-derived, rule-based (non-clustering) "
    "classification, conditioned only on coarse MCBS age (65-74 / 75+) x income "
    "(<$25k / >=$25k) strata, broadcast onto the ACS's finer 4-band x 3-tier "
    "grid. These are NOT county-specific attitude estimates -- MCBS is a "
    "national survey with no county identifier. Attitude segment is assumed "
    "independent of race/ethnicity given age/income (MCBS provides no "
    "race-conditioned segmentation at this granularity).",
    "Population total uses the CMS penetration-file 'eligibles' count "
    "(2024-03, the real Maricopa County 65+ Medicare-eligible denominator), "
    "not an ACS-65+-minus-haircut estimate. ACS marginals supply distribution "
    "shape only.",
    "prior_plan_year1 includes an 'other_or_no_ma_2024' outside option "
    "combining (a) beneficiaries not enrolled in any Maricopa MA plan and "
    "(b) CPSC enrollees in contract/plan combinations outside the 93-plan "
    "landscape_2024 universe (legacy/closed/non-marketed plans). These two "
    "sub-populations cannot be distinguished with available data.",
    "D-SNP plans (snp_type == 'Dual-Eligible') get exactly zero prior "
    "probability for every archetype whose dual_proxy is False -- enforced "
    "as a structural zero in the IPF seed matrix (multiplicative IPF cannot "
    "un-zero a cell), not a soft preference.",
    "'Other' catch-all archetypes fold the long tail (cells outside the top "
    "~95%-cumulative-weight set, capped to keep the total archetype count "
    "in [30, 80]) into one archetype per (age_band, income_tier) combination "
    "with residual weight. Only race_eth and attitude_segment collapse to "
    "'mixed' for these rows -- dual-eligibility status (derived from "
    "income_tier) stays exact.",
]


def _slugify_id(age_band: str, income_tier: str, race_eth: str, attitude_segment: str) -> str:
    return (
        f"a{_AGE_BAND_SLUG[age_band]}-{_INCOME_TIER_SLUG[income_tier]}-"
        f"{_RACE_ETH_SLUG[race_eth]}-{attitude_segment}"
    )


def _load_inputs() -> dict[str, pd.DataFrame]:
    return {
        "acs": pd.read_parquet(settings.INTERIM_DIR / "acs_maricopa.parquet"),
        "mcbs": pd.read_parquet(settings.INTERIM_DIR / "mcbs_subset.parquet"),
        "landscape": pd.read_parquet(settings.INTERIM_DIR / "landscape_2024.parquet"),
        "benefits": pd.read_parquet(settings.INTERIM_DIR / "benefits_2024.parquet"),
        "cpsc": pd.read_parquet(settings.INTERIM_DIR / "cpsc_2024_03.parquet"),
        "penetration": pd.read_parquet(settings.INTERIM_DIR / "penetration_2024_03.parquet"),
    }


def build(output_path: Path | None = None) -> dict:
    """Run the full Phase 2 pipeline and write data/processed/archetypes.json.

    Returns the same dict that gets serialized (``{"metadata": ..., "archetypes": [...]}``).
    """
    data = _load_inputs()

    marginals = acs_marginals.build_marginals(data["acs"])
    segmentation = mcbs_segments.build_segments(data["mcbs"])
    population_total = float(data["penetration"]["eligibles"].iloc[0])

    demo_cells, demo_iterations = cells.build_demographic_cells(marginals, population_total)
    expanded = cells.expand_with_segments(demo_cells, segmentation.stratum_probabilities)
    collapsed = cells.collapse_cells(
        expanded,
        min_count=COLLAPSE_MIN_COUNT,
        max_count=COLLAPSE_MAX_COUNT,
        target_cumulative=COLLAPSE_TARGET_CUMULATIVE,
    ).reset_index(drop=True)

    collapsed["archetype_id"] = [
        _slugify_id(row.age_band, row.income_tier, row.race_eth, row.attitude_segment)
        for row in collapsed.itertuples()
    ]
    if collapsed["archetype_id"].duplicated().any():
        dupes = collapsed.loc[collapsed["archetype_id"].duplicated(), "archetype_id"].tolist()
        raise RuntimeError(f"archetype id collision(s), pipeline bug: {dupes}")

    universe = plan_priors.build_plan_universe(data["landscape"], data["benefits"])
    plan_targets = plan_priors.cpsc_plan_targets(data["cpsc"], universe, eligibles_total=population_total)
    priors, plan_iterations = plan_priors.fit_plan_priors(collapsed, universe, plan_targets, tol=IPF_TOLERANCE)

    archetype_records = []
    for row in collapsed.itertuples():
        aid = row.archetype_id
        weight = float(row.weight)
        record = {
            "id": aid,
            "age_band": row.age_band,
            "income_tier": row.income_tier,
            "race_eth": row.race_eth,
            "attitude_segment": row.attitude_segment,
            "dual_proxy": bool(row.dual_proxy),
            "weight": round(weight, 6),
            "share_of_population": round(weight / population_total, 10),
            "prior_plan_year1": {k: round(v, 10) for k, v in priors[aid].items()},
            "traits": traits.build_traits(pd.Series(row._asdict())),
        }
        archetype_records.append(record)

    archetype_records.sort(key=lambda r: (-r["weight"], r["id"]))

    metadata = {
        "generated_from": {
            "county_fips": settings.COUNTY_FIPS,
            "county_name": settings.COUNTY_NAME,
            "state": settings.STATE_ABBREV,
            "year1": settings.YEAR1,
            "seed": settings.SEED,
            "inputs": [
                "acs_maricopa.parquet",
                "mcbs_subset.parquet",
                "landscape_2024.parquet",
                "benefits_2024.parquet",
                "cpsc_2024_03.parquet",
                "penetration_2024_03.parquet",
            ],
        },
        "population_total": population_total,
        "population_total_source": (
            "penetration_2024_03.parquet 'eligibles' column -- the official CMS "
            "Maricopa County Medicare-eligible denominator for 2024-03. Used as "
            "the IPF joint-weight total in place of an ACS-65+-minus-haircut "
            "estimate; ACS marginals supply distribution shape only."
        ),
        "assumptions": _ASSUMPTIONS,
        "acs_marginals": {
            "age_band_shares": marginals.age_band_shares,
            "race_eth_shares": marginals.race_eth_shares,
            "income_tier_shares": marginals.income_tier_shares,
        },
        "acs_income_tier_cutoffs": marginals.income_tier_metadata,
        "mcbs_segmentation": {
            "national_shares": segmentation.national_shares,
            "n_respondents_used": segmentation.n_respondents_used,
            "note": (
                "National MCBS-derived attitude segments conditioned on coarse "
                "age (65-74 / 75+) x income (<$25k / >=$25k) strata, broadcast "
                "onto the ACS's finer 4x3 age/income grid. NOT county-specific "
                "attitude estimates."
            ),
        },
        "ipf": {
            "demographic_cells_iterations": demo_iterations,
            "plan_priors_iterations": plan_iterations,
            "tolerance": IPF_TOLERANCE,
        },
        "collapse": {
            "min_count": COLLAPSE_MIN_COUNT,
            "max_count": COLLAPSE_MAX_COUNT,
            "target_cumulative": COLLAPSE_TARGET_CUMULATIVE,
        },
        "archetype_count": len(archetype_records),
    }

    result = {"metadata": metadata, "archetypes": archetype_records}

    dest = output_path if output_path is not None else settings.PROCESSED_DIR / "archetypes.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    return result


if __name__ == "__main__":
    result = build()
    meta = result["metadata"]
    archetypes = result["archetypes"]
    print(f"archetypes: {len(archetypes)} (target range [{COLLAPSE_MIN_COUNT}, {COLLAPSE_MAX_COUNT}])")
    print(f"population_total: {meta['population_total']:,.0f} ({meta['population_total_source']})")
    print(f"ipf: demographic_cells_iterations={meta['ipf']['demographic_cells_iterations']} "
          f"plan_priors_iterations={meta['ipf']['plan_priors_iterations']}")
    print(f"mcbs national segment shares: {meta['mcbs_segmentation']['national_shares']}")
    print("top 10 archetypes by weight:")
    for record in archetypes[:10]:
        print(f"  {record['id']:<45} weight={record['weight']:>12,.1f}  share={record['share_of_population']:.4%}")
