"""Phase 6 entrypoint: the pipeline -> app data export (``make export``).

Reads the committed ``data/processed/*.json`` artifacts (plus, via
``choice_model.predict``'s crosswalk logic, ``data/interim/
plan_crosswalk_2024_2025.parquet``) and writes six small, deterministic,
UI-ready JSON files into ``app/src/data/``:

  * ``market.json`` -- both years' plan rosters (trimmed to display fields),
    org-level enrollment rollups, and market totals/eligibles per year.
  * ``backtest.json`` -- the full ``backtest_result.json`` summary + bounds,
    with ``per_plan`` trimmed to the fields the UI needs (the five
    ``shift_*`` fields are dropped -- trivially derivable client-side as
    ``share_2025_X - share_2024``).
  * ``archetypes.json`` -- one compact record per archetype (id,
    demographics, segment, dual_proxy, weight, share_of_population, traits,
    top-5 prior plans by probability) -- explicitly NOT the giant
    ~95-key-per-archetype ``prior_plan_year1`` dict from the source file.
  * ``coefficients.json`` -- verbatim copy; the TS choice-model engine
    (``app/src/lib/choice-model/``) reads this directly at runtime.
  * ``scenario_inputs.json`` -- everything ``/api/scenario`` needs to call
    the TS engine at runtime: the full 2025 plan roster (engine-shaped),
    and per-archetype eligible-plan sets + Year-1 priors re-expressed over
    2025 plan keys. The crosswalk mapping + eligibility renormalization is
    NOT reimplemented here -- it reuses ``choice_model.predict.
    predict_for_archetype`` (the same function Phase 4/5 use), so the
    2025-keyed priors this writes are byte-for-byte the same computation
    ``backtest_result.json`` and ``y2_predictions.json`` are built from.
  * ``personas.json`` -- passthrough of ``data/processed/personas.json``
    (LLM-generated persona backstories) with ``available: true`` added when
    that file exists; ``{"available": false, "personas": []}`` otherwise
    (the LLM pass hasn't run yet as of this writing -- every consumer must
    handle this gracefully and light up automatically once it has).

Every ``build_*`` function below is pure (plain dicts/lists in, plain dict
out) and unit-tested against small synthetic fixtures; ``build_all`` is the
only function that touches disk, and is what real-data integration tests +
``make export`` exercise.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from choice_model import predict
from config.settings import REPO_ROOT, settings

APP_DATA_DIR = REPO_ROOT / "app" / "src" / "data"

# Conservative reading of the "< 2MB" spec: 2,000,000 bytes (decimal MB), not
# the slightly larger 2 * 1024 * 1024 (MiB). Exported/imported by tests too,
# so the cap is asserted in exactly one place.
MAX_ARTIFACT_BYTES = 2_000_000

TOP_PRIOR_PLANS_N = 5

# Trimmed per-plan display fields shared by market.json's plan rosters AND
# scenario_inputs.json's plan roster -- a superset of what the TS engine's
# `Plan` type (app/src/lib/choice-model/types.ts) actually reads
# (plan_key/is_ppo/snp_type/premium_total/moop_inn/star_rating/has_*) plus a
# handful of display-only fields (org_name/plan_name/plan_type). Raw/
# imputation-diagnostic fields (plan_type_raw, star_rating_raw,
# moop_imputation_method, premium_part_c/d, deductible, contract_id,
# plan_id, year) are dropped -- not read by the engine and not shown in the
# UI as currently scoped.
PLAN_DISPLAY_FIELDS = (
    "plan_key",
    "org_name",
    "plan_name",
    "plan_type",
    "is_ppo",
    "snp_type",
    "premium_total",
    "moop_inn",
    "star_rating",
    "has_comprehensive_dental",
    "has_vision",
    "has_hearing_aids",
    "has_otc_or_flex",
    "imputed_moop",
    "imputed_star",
)

# backtest_result.json's PerPlanRecord fields kept for the UI. The five
# shift_* fields are dropped: shift_X == share_2025_X - share_2024 for every
# variant X, so the UI can derive them from the shares already here instead
# of shipping five redundant floats per row.
PER_PLAN_DISPLAY_FIELDS = (
    "plan_key",
    "name",
    "org",
    "enrollment_2024",
    "share_2024",
    "share_2025_actual",
    "share_2025_pred_logit",
    "share_2025_pred_blended",
    "share_2025_naive_nochange",
    "share_2025_naive_trend",
    "abs_error_logit",
    "abs_error_blended",
    "abs_error_naive_nochange",
    "abs_error_naive_trend",
)


# --- small pure helpers -----------------------------------------------------------


def _enrollment_field(year: int, enrollment_month: int = settings.ENROLLMENT_MONTH) -> str:
    return f"enrollment_{year}_{enrollment_month:02d}"


def _trim_plan(plan: dict, enrollment_field: str) -> dict:
    """One plan record -> `PLAN_DISPLAY_FIELDS` plus a generic `enrollment`
    field (renamed from the year-specific `enrollment_<year>_<month>` --
    the caller already knows the year from context, so the year-suffixed
    name would be redundant noise in the trimmed artifact)."""
    trimmed = {field: plan[field] for field in PLAN_DISPLAY_FIELDS}
    trimmed["enrollment"] = plan[enrollment_field]
    return trimmed


def _org_rollups(plans: list[dict], enrollment_field: str) -> list[dict]:
    """Org-level rollups: plan_count, total_enrollment, enrollment-weighted
    avg premium/star rating. Sorted by total_enrollment descending (ties
    broken by org_name) -- deterministic and UI-friendly (biggest orgs
    first)."""
    totals: dict[str, dict] = defaultdict(lambda: {"plan_count": 0, "total_enrollment": 0.0, "premium_sum": 0.0, "star_sum": 0.0})
    for plan in plans:
        agg = totals[plan["org_name"]]
        agg["plan_count"] += 1
        agg["total_enrollment"] += plan[enrollment_field]
        agg["premium_sum"] += plan["premium_total"]
        agg["star_sum"] += plan["star_rating"]

    rollups = [
        {
            "org_name": org,
            "plan_count": agg["plan_count"],
            "total_enrollment": agg["total_enrollment"],
            "avg_premium": agg["premium_sum"] / agg["plan_count"],
            "avg_star_rating": agg["star_sum"] / agg["plan_count"],
        }
        for org, agg in totals.items()
    ]
    return sorted(rollups, key=lambda r: (-r["total_enrollment"], r["org_name"]))


def _market_totals(plans: list[dict], enrollment_field: str, eligibles: float) -> dict:
    total_enrollment = sum(plan[enrollment_field] for plan in plans)
    return {
        "plan_count": len(plans),
        "total_ma_enrollment": total_enrollment,
        "eligibles": eligibles,
        "ma_penetration": (total_enrollment / eligibles) if eligibles else None,
    }


def _top_prior_plans(prior_plan_year1: dict[str, float], outside_key: str, n: int = TOP_PRIOR_PLANS_N) -> list[dict]:
    """Top-`n` REAL plans (never the outside option) by Year-1 prior
    probability, descending (ties broken by plan_key for determinism). The
    outside option's own share is reported separately (see
    `prior_outside_share` in `build_archetypes`) rather than competing for
    one of the n slots."""
    plan_only = [(key, prob) for key, prob in prior_plan_year1.items() if key != outside_key]
    plan_only.sort(key=lambda item: (-item[1], item[0]))
    return [{"plan_key": key, "prior_prob": prob} for key, prob in plan_only[:n]]


def _nonzero(mapping: dict[str, float]) -> dict[str, float]:
    """Drops exactly-zero entries. Safe because every consumer (the TS
    engine's `renormalizePriorPlan` / `choiceProbabilities`) already treats
    a MISSING key as probability 0.0 -- see engine.ts / utility.ts -- so
    dropping explicit zeros changes nothing functionally while shrinking
    scenario_inputs.json (most plans carry zero Year-1 prior mass for most
    archetypes)."""
    return {key: value for key, value in mapping.items() if value > 0.0}


# --- market.json -------------------------------------------------------------------


def build_market(plans_2024_file: dict, plans_2025_file: dict, backtest_result: dict) -> dict:
    """`data/processed/plans_2024.json` + `plans_2025.json` + `backtest_result.
    json`'s `eligibles_2024`/`eligibles_2025` -> market.json's dict shape."""
    plans_2024 = plans_2024_file["plans"]
    plans_2025 = plans_2025_file["plans"]
    ef_2024 = _enrollment_field(settings.YEAR1)
    ef_2025 = _enrollment_field(settings.YEAR2)
    eligibles_2024 = backtest_result["metadata"]["eligibles_2024"]
    eligibles_2025 = backtest_result["metadata"]["eligibles_2025"]

    return {
        "metadata": {
            "year1": settings.YEAR1,
            "year2": settings.YEAR2,
            "enrollment_month": settings.ENROLLMENT_MONTH,
        },
        "plans": {
            str(settings.YEAR1): sorted((_trim_plan(p, ef_2024) for p in plans_2024), key=lambda p: p["plan_key"]),
            str(settings.YEAR2): sorted((_trim_plan(p, ef_2025) for p in plans_2025), key=lambda p: p["plan_key"]),
        },
        "org_rollups": {
            str(settings.YEAR1): _org_rollups(plans_2024, ef_2024),
            str(settings.YEAR2): _org_rollups(plans_2025, ef_2025),
        },
        "market_totals": {
            str(settings.YEAR1): _market_totals(plans_2024, ef_2024, eligibles_2024),
            str(settings.YEAR2): _market_totals(plans_2025, ef_2025, eligibles_2025),
        },
    }


# --- backtest.json ------------------------------------------------------------------


def build_backtest(backtest_result: dict) -> dict:
    """`data/processed/backtest_result.json` -> backtest.json's dict shape:
    metadata + summary kept verbatim, per_plan trimmed to
    `PER_PLAN_DISPLAY_FIELDS`, bounds kept verbatim."""
    per_plan = sorted(
        ({field: row[field] for field in PER_PLAN_DISPLAY_FIELDS} for row in backtest_result["per_plan"]),
        key=lambda row: row["plan_key"],
    )
    return {
        "metadata": backtest_result["metadata"],
        "summary": backtest_result["summary"],
        "per_plan": per_plan,
        "bounds": backtest_result["bounds"],
    }


# --- archetypes.json -----------------------------------------------------------------


def build_archetypes(archetypes_file: dict, outside_key: str = predict.OUTSIDE_KEY_YEAR1) -> dict:
    """`data/processed/archetypes.json` -> archetypes.json's dict shape: one
    compact record per archetype, no giant prior_plan_year1 dict (only the
    top-`TOP_PRIOR_PLANS_N` plans by prior probability, plus the outside
    option's own share, are kept)."""
    archetypes = archetypes_file["archetypes"]
    source_metadata = archetypes_file.get("metadata", {})

    records = []
    for archetype in archetypes:
        prior = archetype.get("prior_plan_year1", {})
        records.append(
            {
                "id": archetype["id"],
                "demographics": {
                    "age_band": archetype["age_band"],
                    "income_tier": archetype.get("income_tier"),
                    "race_eth": archetype.get("race_eth"),
                },
                "segment": archetype["attitude_segment"],
                "dual_proxy": archetype["dual_proxy"],
                "weight": archetype["weight"],
                "share_of_population": archetype.get("share_of_population"),
                "traits": archetype.get("traits", []),
                "prior_outside_share": prior.get(outside_key, 0.0),
                "top_prior_plans": _top_prior_plans(prior, outside_key),
            }
        )
    records.sort(key=lambda r: r["id"])

    return {
        "metadata": {
            "archetype_count": source_metadata.get("archetype_count", len(records)),
            "population_total": source_metadata.get("population_total"),
            "top_prior_plans_n": TOP_PRIOR_PLANS_N,
            "outside_option_key": outside_key,
        },
        "archetypes": records,
    }


# --- coefficients.json ---------------------------------------------------------------


def build_coefficients(coefficients_file: dict) -> dict:
    """Verbatim copy -- the TS choice-model engine reads this file directly
    at runtime (see app/src/lib/choice-model/types.ts's `CoefficientsFile`),
    so nothing here should be renamed, dropped, or restructured."""
    return coefficients_file


# --- scenario_inputs.json -------------------------------------------------------------


def build_scenario_inputs(
    archetypes: list[dict],
    plans_2025: list[dict],
    base_coefficients: dict[str, float],
    crosswalk_map: dict[str, dict],
    outside_key_year1: str = predict.OUTSIDE_KEY_YEAR1,
    outside_key_year2: str = predict.OUTSIDE_KEY_YEAR2,
) -> dict:
    """Everything `/api/scenario` needs to call the TS choice-model engine
    at runtime, without reimplementing `choice_model.predict`'s crosswalk
    logic: the full 2025 plan roster (engine-shaped) plus, per archetype,
    its eligible 2025 plan_keys and its Year-1 prior re-expressed over 2025
    plan keys (via `predict.predict_for_archetype` -- the same call Phase
    4/5 make; only its `renormalized_prior` / `eligible_plan_keys` outputs
    are kept here, `probs` is recomputed client-side by the TS engine so
    scenario deltas can be applied)."""
    ef_2025 = _enrollment_field(settings.YEAR2)
    trimmed_plans = sorted((_trim_plan(p, ef_2025) for p in plans_2025), key=lambda p: p["plan_key"])

    archetype_records = []
    for archetype in archetypes:
        result = predict.predict_for_archetype(
            archetype, plans_2025, base_coefficients, crosswalk_map, outside_key_year1, outside_key_year2
        )
        archetype_records.append(
            {
                "id": archetype["id"],
                "age_band": archetype["age_band"],
                "attitude_segment": archetype["attitude_segment"],
                "dual_proxy": archetype["dual_proxy"],
                "weight": archetype["weight"],
                "eligible_plan_keys": result["eligible_plan_keys"],
                "prior_plan_year1": _nonzero(result["renormalized_prior"]),
            }
        )
    archetype_records.sort(key=lambda r: r["id"])

    return {
        "metadata": {
            "year": settings.YEAR2,
            "outside_option_key": outside_key_year2,
        },
        "outside_option_key": outside_key_year2,
        "plans": trimmed_plans,
        "archetypes": archetype_records,
    }


# --- personas.json ---------------------------------------------------------------------


def build_personas(personas_file: dict | None) -> dict:
    """`data/processed/personas.json` (if it exists) -> personas.json's dict
    shape, with `available: true` added; `{"available": false, "personas":
    []}` when `personas_file` is `None` (the LLM pass hasn't run yet)."""
    if personas_file is None:
        return {"available": False, "personas": []}
    return {
        "available": True,
        "metadata": personas_file.get("metadata", {}),
        "personas": personas_file.get("personas", []),
    }


# --- real-file I/O -------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write_json(path: Path, data: dict) -> int:
    """Writes `data` deterministically (sorted keys, stable 2-space indent,
    matching every other `data/processed/*.json` writer in this pipeline)
    and returns the byte size written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.write_text(text)
    return len(text.encode("utf-8"))


def build_all(processed_dir: Path | None = None, app_data_dir: Path | None = None) -> dict[str, dict]:
    """Reads the real committed `data/processed/*.json` artifacts (plus the
    real committed `data/interim/plan_crosswalk_2024_2025.parquet`, via
    `choice_model.predict.load_crosswalk_map`), builds all six export
    artifacts, and writes them to `app_data_dir` (default `APP_DATA_DIR`).

    Returns `{filename: data}` for every artifact written (the caller can
    inspect sizes/contents without re-reading from disk).
    """
    src_dir = processed_dir if processed_dir is not None else settings.PROCESSED_DIR
    dest_dir = app_data_dir if app_data_dir is not None else APP_DATA_DIR

    plans_2024_file = _load_json(src_dir / f"plans_{settings.YEAR1}.json")
    plans_2025_file = _load_json(src_dir / f"plans_{settings.YEAR2}.json")
    archetypes_file = _load_json(src_dir / "archetypes.json")
    coefficients_file = _load_json(src_dir / "coefficients.json")
    backtest_result = _load_json(src_dir / "backtest_result.json")

    personas_path = src_dir / "personas.json"
    personas_file = _load_json(personas_path) if personas_path.exists() else None

    crosswalk_map = predict.load_crosswalk_map()

    artifacts = {
        "market.json": build_market(plans_2024_file, plans_2025_file, backtest_result),
        "backtest.json": build_backtest(backtest_result),
        "archetypes.json": build_archetypes(archetypes_file),
        "coefficients.json": build_coefficients(coefficients_file),
        "scenario_inputs.json": build_scenario_inputs(
            archetypes_file["archetypes"],
            plans_2025_file["plans"],
            coefficients_file["base_coefficients"],
            crosswalk_map,
        ),
        "personas.json": build_personas(personas_file),
    }

    for filename, data in artifacts.items():
        _write_json(dest_dir / filename, data)

    return artifacts


if __name__ == "__main__":
    out = build_all()
    for filename, data in out.items():
        size = (APP_DATA_DIR / filename).stat().st_size
        over = " ** OVER MAX_ARTIFACT_BYTES **" if size > MAX_ARTIFACT_BYTES else ""
        print(f"{filename}: {size:,} bytes{over}")
