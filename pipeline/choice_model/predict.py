"""Phase 4 Year-2 (2025) logit choice-model baseline.

Reused by Phase 5 (the LLM persona blend) and, eventually, the TypeScript
port: this module is the pure forward-evaluation counterpart to
``choice_model/calibrate.py`` (which *fits* the base coefficients against
2024). Here the (already-fitted) coefficients from ``coefficients.json`` are
evaluated forward against the 2025 plan universe.

The one genuinely new piece of logic versus Phase 3 is the crosswalk: each
archetype's ``prior_plan_year1`` (a probability distribution over 2024 plan
keys + the 2024 outside option) has to be re-expressed over 2025 plan keys
before it can serve as the inertia term in ``utility.plan_utility`` /
``utility.outside_utility``. ``data/interim/plan_crosswalk_2024_2025.parquet``
maps each 2024 (old) plan to its 2025 (new) disposition:

  * "renewed" / "renumbered" / "consolidated" -- prior mass moves to the
    successor plan_key. Consolidated old plans that share one successor
    (e.g. two merged plans) have their prior mass summed onto that one
    successor key.
  * "terminated" -- the plan has no 2025 successor. Per the Phase 4 spec,
    this mass gets **no plan inertia at all**: it is not redistributed onto
    any particular surviving plan (that would fabricate brand loyalty to an
    arbitrary "nearest" competitor) and it is not folded into the outside
    option either (leaving Medicare entirely is a different, stronger claim
    than "your plan disappeared"). It is tracked under
    :data:`NO_SUCCESSOR_BUCKET`, a key that is deliberately neither a real
    2025 plan_key nor the outside key -- when the resulting dict is fed
    through ``choice_sets.renormalize_prior_plan`` (as every caller here
    does), that bucket is dropped exactly like any other unrecognized key,
    and the remaining eligible mass renormalizes proportionally across
    itself. No single plan is boosted by another plan's termination.
  * A 2024 plan_key with no crosswalk row at all is treated the same way as
    "terminated" (conservative default; shouldn't occur against the real
    committed 93-plan 2024 landscape, where the crosswalk has exactly one
    row per plan).

The 2024 outside option (``OUTSIDE_KEY_YEAR1``, the Phase 2 constant
``other_or_no_ma_2024``) maps to a distinct 2025 outside option key,
``OUTSIDE_KEY_YEAR2``. They are intentionally different strings: the 2025
outside bucket is a fresh evaluation target (this year's "stayed out of
MA"/unresolved residual), not a literal continuation of the 2024 one, even
though nearly all of that mass carries forward via the mapping.

Everything below the crosswalk plumbing simply reuses the Phase 3 machinery
unchanged: ``choice_sets.eligible_plans`` for the 2025 D-SNP/I-SNP/C-SNP
hard filters, ``choice_sets.renormalize_prior_plan`` to zero ineligible mass
and renormalize the (crosswalked) prior to sum to 1, and
``utility.choice_probabilities`` for the softmax itself.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from archetypes.plan_priors import OUTSIDE_PLAN_KEY
from choice_model import choice_sets, utility
from config.settings import settings

OUTSIDE_KEY_YEAR1 = OUTSIDE_PLAN_KEY  # "other_or_no_ma_2024" (Phase 2's constant, reused not re-literaled)
OUTSIDE_KEY_YEAR2 = "other_or_no_ma_2025"

TERMINATED_DISPOSITION = "terminated"
TERMINATED_MARKER = "TERMINATED"

# Sentinel bucket key for Year-1 prior mass whose 2024 plan has no 2025
# successor. Deliberately not a real plan_key and not OUTSIDE_KEY_YEAR2, so
# it is dropped (not redistributed onto any plan or the outside option) by
# choice_sets.renormalize_prior_plan, which excludes any key it doesn't
# recognize as eligible-or-outside.
NO_SUCCESSOR_BUCKET = "no_successor_terminated_2024"

CROSSWALK_FILENAME = "plan_crosswalk_2024_2025.parquet"


# --- crosswalk map ----------------------------------------------------------


def crosswalk_map_from_rows(rows: list[dict]) -> dict[str, dict]:
    """2024 plan_key -> {"disposition": str, "new_plan_key": str | None}.

    ``rows`` are records shaped like ``plan_crosswalk_2024_2025.parquet``
    (old_contract_id/old_plan_id/new_contract_id/new_plan_id/disposition).
    ``new_plan_key`` is ``None`` for terminated plans (CMS marks these with
    the literal string ``"TERMINATED"`` in both new_contract_id/new_plan_id;
    ``disposition == "terminated"`` is checked too, defense in depth).
    """
    mapping: dict[str, dict] = {}
    for row in rows:
        old_key = f"{row['old_contract_id']}-{row['old_plan_id']}"
        disposition = row["disposition"]
        terminated = disposition == TERMINATED_DISPOSITION or row["new_contract_id"] == TERMINATED_MARKER or row["new_plan_id"] == TERMINATED_MARKER
        new_key = None if terminated else f"{row['new_contract_id']}-{row['new_plan_id']}"
        mapping[old_key] = {"disposition": disposition, "new_plan_key": new_key}
    return mapping


def load_crosswalk_map(path: Path | None = None) -> dict[str, dict]:
    """Load + convert the real committed crosswalk parquet (default path)."""
    crosswalk_path = path if path is not None else settings.INTERIM_DIR / CROSSWALK_FILENAME
    df = pd.read_parquet(crosswalk_path)
    return crosswalk_map_from_rows(df.to_dict(orient="records"))


# --- prior mapping ------------------------------------------------------------


def map_prior_year1_to_year2(
    prior_plan_year1: dict[str, float],
    crosswalk_map: dict[str, dict],
    outside_key_year1: str = OUTSIDE_KEY_YEAR1,
    outside_key_year2: str = OUTSIDE_KEY_YEAR2,
) -> dict[str, float]:
    """One archetype's Year-1 prior, re-expressed over 2025 plan keys.

    Not necessarily summing to 1 -- terminated-plan mass is dropped into
    ``NO_SUCCESSOR_BUCKET`` rather than redistributed (see module
    docstring). Callers that need a valid distribution should run the
    result through ``choice_sets.renormalize_prior_plan`` against the 2025
    plan list and outside key, which drops that bucket and renormalizes the
    remainder -- see ``predict_for_archetype`` below.
    """
    year2_prior: dict[str, float] = {}
    no_successor_mass = 0.0

    for key, prob in prior_plan_year1.items():
        if key == outside_key_year1:
            year2_prior[outside_key_year2] = year2_prior.get(outside_key_year2, 0.0) + prob
            continue
        entry = crosswalk_map.get(key)
        if entry is None or entry["new_plan_key"] is None:
            no_successor_mass += prob
            continue
        new_key = entry["new_plan_key"]
        year2_prior[new_key] = year2_prior.get(new_key, 0.0) + prob

    year2_prior[NO_SUCCESSOR_BUCKET] = no_successor_mass
    return year2_prior


# --- per-archetype / aggregate prediction --------------------------------------


def predict_for_archetype(
    archetype: dict,
    plans_2025: list[dict],
    base_coefficients: dict[str, float],
    crosswalk_map: dict[str, dict],
    outside_key_year1: str = OUTSIDE_KEY_YEAR1,
    outside_key_year2: str = OUTSIDE_KEY_YEAR2,
) -> dict:
    """Pure per-archetype Year-2 logit result.

    Returns ``{"probs": {...}, "renormalized_prior": {...},
    "eligible_plan_keys": [...]}``. ``renormalized_prior`` and
    ``eligible_plan_keys`` are exposed (not just the final probs) because
    Phase 4's persona prompts need both: the crosswalked prior to find "the
    plan holding this archetype's largest carried-forward mass", and the
    eligible set to keep the LLM's consideration set D-SNP/I-SNP/C-SNP-safe.
    """
    year2_prior_raw = map_prior_year1_to_year2(
        archetype.get("prior_plan_year1", {}), crosswalk_map, outside_key_year1, outside_key_year2
    )
    eligible = choice_sets.eligible_plans(archetype, plans_2025)
    renormalized_prior = choice_sets.renormalize_prior_plan(year2_prior_raw, archetype, plans_2025, outside_key_year2)
    probs = utility.choice_probabilities(
        base_coefficients, archetype["attitude_segment"], eligible, renormalized_prior, outside_key_year2
    )
    return {
        "probs": probs,
        "renormalized_prior": renormalized_prior,
        "eligible_plan_keys": [plan["plan_key"] for plan in eligible],
    }


def aggregate_weighted_shares(archetypes: list[dict], per_archetype_probs: dict[str, dict[str, float]]) -> dict[str, float]:
    """Population-weight-averaged shares: sum(weight * prob) / sum(weight)."""
    totals: dict[str, float] = {}
    total_weight = 0.0
    for archetype in archetypes:
        probs = per_archetype_probs.get(archetype["id"], {})
        weight = float(archetype["weight"])
        total_weight += weight
        for key, prob in probs.items():
            totals[key] = totals.get(key, 0.0) + weight * prob
    if total_weight <= 0:
        return {}
    return {key: value / total_weight for key, value in totals.items()}


def predict_all(
    archetypes: list[dict],
    plans_2025: list[dict],
    base_coefficients: dict[str, float],
    crosswalk_map: dict[str, dict],
    outside_key_year1: str = OUTSIDE_KEY_YEAR1,
    outside_key_year2: str = OUTSIDE_KEY_YEAR2,
) -> dict:
    """Per-archetype Year-2 logit results + population-weighted aggregate shares."""
    per_archetype = {
        archetype["id"]: predict_for_archetype(
            archetype, plans_2025, base_coefficients, crosswalk_map, outside_key_year1, outside_key_year2
        )
        for archetype in archetypes
    }
    aggregate_shares = aggregate_weighted_shares(archetypes, {aid: v["probs"] for aid, v in per_archetype.items()})
    return {"per_archetype": per_archetype, "aggregate_shares": aggregate_shares}


# --- diagnostics ----------------------------------------------------------------


def terminated_mass_by_archetype(
    archetypes: list[dict],
    crosswalk_map: dict[str, dict],
    outside_key_year1: str = OUTSIDE_KEY_YEAR1,
) -> dict[str, float]:
    """Diagnostic only: each archetype's raw (pre-renormalization) Year-1
    prior mass that mapped to a terminated (no-successor) 2024 plan."""
    result = {}
    for archetype in archetypes:
        mapped = map_prior_year1_to_year2(archetype.get("prior_plan_year1", {}), crosswalk_map, outside_key_year1)
        result[archetype["id"]] = mapped.get(NO_SUCCESSOR_BUCKET, 0.0)
    return result
