"""Phase 5 entrypoint: the backtest orchestrator (``make backtest``).

Wires together every other ``backtest/*`` module plus the reused Phase
3/4 machinery into ``data/processed/backtest_result.json``:

  * actual 2024/2025 shares from CMS interim data (``actuals.py``),
  * the Year-2 logit prediction (``choice_model.predict``, unchanged from
    Phase 4) and, when ``data/processed/y2_predictions.json`` already
    exists (i.e. the LLM persona pass has run), the blended prediction
    alongside it,
  * both naive baselines (``baselines.py`` -- no_change always, trend when
    the March-2023 CPSC snapshot downloads successfully),
  * per-plan/aggregate scoring (``metrics.py``) and the explicit,
    never-hand-set ``beats_naive`` verdict,
  * Monte Carlo p10/p50/p90 bounds (``bounds.py``) for the "primary" model
    variant (blended if present, else logit).

Runs in **logit-only mode** right now (no ``y2_predictions.json`` yet, since
the LLM persona pass hasn't been run against a live API key) -- every
``*_blended`` field in the output is ``null`` and ``model_variants_included``
reflects that. Re-running after ``make personas`` succeeds picks up the
blended variant automatically with no code change: this module never
special-cases "logit-only" beyond checking whether the file exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd

from backtest import actuals, baselines, bounds, metrics
from backtest.schemas import BacktestResult
from choice_model import predict
from config.settings import settings
from ingest.base import sha256_of_file

RESULT_FILENAME = "backtest_result.json"

OUTSIDE1 = predict.OUTSIDE_KEY_YEAR1
OUTSIDE2 = predict.OUTSIDE_KEY_YEAR2
OUTSIDE_DISPLAY_NAME = "Outside MA (traditional Medicare / unresolved)"

NAIVE_VARIANT_NAMES = ("no_change", "trend")
MODEL_VARIANT_NAMES = ("logit", "blended")


# --- small pure helpers ------------------------------------------------------------


def _map_counts_to_2025(
    counts_2024: dict[str, float], crosswalk_map: dict[str, dict]
) -> tuple[dict[str, float], float]:
    """2024-keyed raw enrollment counts -> 2025-keyed counts (reuses
    ``predict.map_prior_year1_to_year2`` -- it's agnostic to whether the
    "mass" being mapped is a probability or a raw count). Returns
    ``(mapped_counts, terminated_count)`` -- terminated_count is the raw
    2024 enrollment that had no 2025 successor (dropped from
    ``mapped_counts`` entirely, not redistributed -- see backtest/baselines.py
    module docstring for why the ground-truth share_2024 basis and the
    no_change/trend *predictions* deliberately handle this differently)."""
    mapped = predict.map_prior_year1_to_year2(counts_2024, crosswalk_map, OUTSIDE1, OUTSIDE2)
    terminated = mapped.pop(predict.NO_SUCCESSOR_BUCKET, 0.0)
    return mapped, terminated


def _suppressed_both_years(
    cpsc_2024_df: pd.DataFrame,
    cpsc_2025_df: pd.DataFrame,
    plan_keys_2024: list[str],
    plan_keys_2025: list[str],
    crosswalk_map: dict[str, dict],
) -> set[str]:
    """2025 plan keys that were CMS-suppressed in 2025 AND whose crosswalk-
    mapped 2024 predecessor(s) were also suppressed in 2024 -- excluded from
    ``metrics.directional_accuracy`` per spec (no reliable actual-shift
    signal either year)."""
    suppressed_2025 = actuals.suppressed_plan_keys(cpsc_2025_df, plan_keys_2025)
    suppressed_2024_raw = actuals.suppressed_plan_keys(cpsc_2024_df, plan_keys_2024)

    suppressed_2024_mapped: set[str] = set()
    for old_key in suppressed_2024_raw:
        entry = crosswalk_map.get(old_key)
        if entry is not None and entry["new_plan_key"] is not None:
            suppressed_2024_mapped.add(entry["new_plan_key"])

    return suppressed_2025 & suppressed_2024_mapped


def _try_build_trend_baseline(
    share_2024_by_2024key: dict[str, float],
    plans_2024: list[dict],
    crosswalk_map: dict[str, dict],
    eligibles_2024: float,
) -> tuple[dict[str, float] | None, dict]:
    """Attempts the full trend-baseline pipeline (2023 CPSC download ->
    parse -> extrapolate -> crosswalk-map). Returns ``(trend_shares_or_None,
    diagnostics_dict)`` -- diagnostics always documents what was tried and
    why it did or didn't succeed, per the spec's "document trend as
    unavailable" requirement on structural failure.
    """
    diagnostics: dict = {"attempted": True}
    try:
        record = baselines.ensure_cpsc_2023_ingested()
        diagnostics["download"] = {
            "filename": record.filename,
            "skipped_cached": record.skipped_cached,
            "sha256": record.sha256,
            "bytes": record.bytes,
        }
        cpsc_2023_df = baselines.load_or_parse_cpsc_2023()
    except (RuntimeError, OSError, httpx.HTTPError) as exc:
        diagnostics["available"] = False
        diagnostics["unavailable_reason"] = f"{type(exc).__name__}: {exc}"
        return None, diagnostics

    plan_keys_2024 = [plan["plan_key"] for plan in plans_2024]
    counts_2023 = actuals.enrollment_by_plan(cpsc_2023_df, plan_keys_2024)
    share_2023_by_2024key = {key: value / eligibles_2024 for key, value in counts_2023.items()}
    # Outside/residual 2023 share, on the SAME (2024-eligibles) denominator
    # basis as the plan shares above -- see baselines.py module docstring
    # for why there's no genuine 2023 eligibles/outside count available.
    known_2023_share = sum(share_2023_by_2024key.values())
    share_2023_by_2024key[OUTSIDE1] = max(0.0, 1.0 - known_2023_share)

    trend_shares = baselines.trend_baseline(share_2024_by_2024key, share_2023_by_2024key, crosswalk_map)
    diagnostics["available"] = True
    diagnostics["n_2024_plans_with_2023_row"] = int(sum(1 for k in plan_keys_2024 if counts_2023.get(k, 0.0) > 0))
    return trend_shares, diagnostics


# --- orchestration -----------------------------------------------------------------


def _load_real_inputs() -> dict:
    archetypes = json.loads((settings.PROCESSED_DIR / "archetypes.json").read_text())["archetypes"]
    plans_2024 = json.loads((settings.PROCESSED_DIR / f"plans_{settings.YEAR1}.json").read_text())["plans"]
    plans_2025 = json.loads((settings.PROCESSED_DIR / f"plans_{settings.YEAR2}.json").read_text())["plans"]
    coefficients = json.loads((settings.PROCESSED_DIR / "coefficients.json").read_text())
    crosswalk_map = predict.load_crosswalk_map()

    cpsc_2024_df = pd.read_parquet(settings.INTERIM_DIR / "cpsc_2024_03.parquet")
    cpsc_2025_df = pd.read_parquet(settings.INTERIM_DIR / "cpsc_2025_03.parquet")
    penetration_2024_df = pd.read_parquet(settings.INTERIM_DIR / "penetration_2024_03.parquet")
    penetration_2025_df = pd.read_parquet(settings.INTERIM_DIR / "penetration_2025_03.parquet")

    y2_predictions_path = settings.PROCESSED_DIR / "y2_predictions.json"
    y2_predictions = json.loads(y2_predictions_path.read_text()) if y2_predictions_path.exists() else None

    personas_path = settings.PROCESSED_DIR / "personas.json"
    personas = json.loads(personas_path.read_text())["personas"] if personas_path.exists() else None

    return {
        "archetypes": archetypes,
        "plans_2024": plans_2024,
        "plans_2025": plans_2025,
        "coefficients": coefficients,
        "crosswalk_map": crosswalk_map,
        "cpsc_2024_df": cpsc_2024_df,
        "cpsc_2025_df": cpsc_2025_df,
        "penetration_2024_df": penetration_2024_df,
        "penetration_2025_df": penetration_2025_df,
        "y2_predictions": y2_predictions,
        "personas": personas,
    }


def run_backtest(
    archetypes: list[dict],
    plans_2024: list[dict],
    plans_2025: list[dict],
    coefficients: dict,
    crosswalk_map: dict[str, dict],
    cpsc_2024_df: pd.DataFrame,
    cpsc_2025_df: pd.DataFrame,
    penetration_2024_df: pd.DataFrame,
    penetration_2025_df: pd.DataFrame,
    y2_predictions: dict | None = None,
    personas: list[dict] | None = None,
    n_bounds_draws: int = bounds.N_DRAWS_DEFAULT,
    seed: int = settings.SEED,
    attempt_trend: bool = True,
) -> dict:
    """Runs the full Phase 5 backtest and returns the ``backtest_result.json``
    dict (not yet written -- see ``build`` below). Pure given its inputs
    except for one network call (the on-demand 2023 CPSC download inside
    the trend-baseline attempt, skippable via ``attempt_trend=False``)."""
    plan_keys_2024 = [plan["plan_key"] for plan in plans_2024]
    plan_keys_2025 = [plan["plan_key"] for plan in plans_2025]
    plans_2025_by_key = {plan["plan_key"]: plan for plan in plans_2025}

    # --- 2024 ground truth (denominator + baseline input) ---------------------
    eligibles_2024 = actuals.eligibles_total(penetration_2024_df)
    counts_2024_by_2024key = actuals.actual_counts(cpsc_2024_df, penetration_2024_df, plan_keys_2024, OUTSIDE1)
    share_2024_by_2024key = {key: value / eligibles_2024 for key, value in counts_2024_by_2024key.items()}

    enrollment_2024_2025keyed, terminated_count_2024 = _map_counts_to_2025(counts_2024_by_2024key, crosswalk_map)
    share_2024_2025keyed = {key: value / eligibles_2024 for key, value in enrollment_2024_2025keyed.items()}

    # --- 2025 actual ------------------------------------------------------------
    actual_2025_shares = actuals.actual_shares(cpsc_2025_df, penetration_2025_df, plan_keys_2025, OUTSIDE2)

    # --- model predictions --------------------------------------------------------
    base_coefficients = coefficients["base_coefficients"]
    logit_result = predict.predict_all(archetypes, plans_2025, base_coefficients, crosswalk_map)
    logit_shares = logit_result["aggregate_shares"]

    blended_shares: dict[str, float] | None = None
    if y2_predictions is not None:
        blended_shares = y2_predictions["aggregate_shares"]["blended"]

    # --- naive baselines ------------------------------------------------------------
    no_change_shares = baselines.no_change_baseline(share_2024_by_2024key, crosswalk_map)

    trend_shares: dict[str, float] | None = None
    trend_diagnostics: dict = {"attempted": False}
    if attempt_trend:
        trend_shares, trend_diagnostics = _try_build_trend_baseline(
            share_2024_by_2024key, plans_2024, crosswalk_map, eligibles_2024
        )

    # --- suppression exclusion set for directional accuracy -------------------------
    suppressed_both_years = _suppressed_both_years(cpsc_2024_df, cpsc_2025_df, plan_keys_2024, plan_keys_2025, crosswalk_map)

    # --- per-plan rows ----------------------------------------------------------------
    row_keys = [*plan_keys_2025, OUTSIDE2]
    predicted_by_variant: dict[str, dict[str, float] | None] = {
        "logit": logit_shares,
        "blended": blended_shares,
        "no_change": no_change_shares,
        "trend": trend_shares,
    }

    per_plan: list[dict] = []
    for key in row_keys:
        plan = plans_2025_by_key.get(key)
        name = plan["plan_name"] if plan is not None else OUTSIDE_DISPLAY_NAME
        org = plan["org_name"] if plan is not None else None

        enr24 = enrollment_2024_2025keyed.get(key, 0.0)
        sh24 = share_2024_2025keyed.get(key, 0.0)
        sh25_actual = actual_2025_shares.get(key, 0.0)
        sh25_logit = logit_shares.get(key, 0.0)
        # .get(key, 0.0) -- not .get(key) -- when the variant WAS computed
        # this run: a brand-new 2025 plan (no 2024 predecessor, so it's
        # absent from a crosswalk-derived dict) genuinely has 0.0 predicted
        # share under that variant, which is a different fact from "this
        # variant wasn't computed at all" (the None case, gated on the dict
        # itself being None).
        sh25_blended = blended_shares.get(key, 0.0) if blended_shares is not None else None
        sh25_nochange = no_change_shares.get(key, 0.0)
        sh25_trend = trend_shares.get(key, 0.0) if trend_shares is not None else None

        per_plan.append(
            {
                "plan_key": key,
                "name": name,
                "org": org,
                "enrollment_2024": enr24,
                "share_2024": sh24,
                "share_2025_actual": sh25_actual,
                "share_2025_pred_logit": sh25_logit,
                "share_2025_pred_blended": sh25_blended,
                "share_2025_naive_nochange": sh25_nochange,
                "share_2025_naive_trend": sh25_trend,
                "shift_actual": sh25_actual - sh24,
                "shift_pred_logit": sh25_logit - sh24,
                "shift_pred_blended": (sh25_blended - sh24) if sh25_blended is not None else None,
                "shift_naive_nochange": sh25_nochange - sh24,
                "shift_naive_trend": (sh25_trend - sh24) if sh25_trend is not None else None,
                "abs_error_logit": abs(sh25_logit - sh25_actual),
                "abs_error_blended": (abs(sh25_blended - sh25_actual) if sh25_blended is not None else None),
                "abs_error_naive_nochange": abs(sh25_nochange - sh25_actual),
                "abs_error_naive_trend": (abs(sh25_trend - sh25_actual) if sh25_trend is not None else None),
            }
        )

    # --- summary metrics, per variant ---------------------------------------------------
    weighted_mae: dict[str, float | None] = {}
    outside_share_error: dict[str, float | None] = {}
    directional_accuracy: dict[str, float | None] = {}

    for variant, predicted in predicted_by_variant.items():
        if predicted is None:
            weighted_mae[variant] = None
            outside_share_error[variant] = None
            directional_accuracy[variant] = None
            continue
        weighted_mae[variant] = metrics.weighted_mae(
            predicted, actual_2025_shares, weights=enrollment_2024_2025keyed, exclude_keys={OUTSIDE2}
        )
        outside_share_error[variant] = abs(predicted.get(OUTSIDE2, 0.0) - actual_2025_shares.get(OUTSIDE2, 0.0))

        predicted_shift = metrics.share_shift(predicted, share_2024_2025keyed)
        actual_shift = metrics.share_shift(actual_2025_shares, share_2024_2025keyed)
        directional_accuracy[variant] = metrics.directional_accuracy(
            predicted_shift, actual_shift, suppressed_both_years=suppressed_both_years, keys=plan_keys_2025
        )

    best_naive_name = metrics.select_best_naive({name: weighted_mae[name] for name in NAIVE_VARIANT_NAMES})
    beats_naive = {
        variant: metrics.beats_naive(
            weighted_mae[variant],
            directional_accuracy[variant],
            weighted_mae[best_naive_name],
            directional_accuracy[best_naive_name],
        )
        for variant in MODEL_VARIANT_NAMES
    }

    # --- Monte Carlo bounds (primary variant: blended if available, else logit) --------
    primary_variant = "blended" if blended_shares is not None else "logit"
    blend_inputs = None
    if primary_variant == "blended":
        personas_by_id = {p["id"]: p for p in (personas or [])}
        blend_inputs = {
            aid: {
                "ranked_plan_keys": persona["ranked_plan_keys"],
                "switching_propensity": persona["switching_propensity"],
            }
            for aid, persona in personas_by_id.items()
        }

    bounds_result = bounds.run_bounds(
        archetypes,
        plans_2025,
        base_coefficients,
        crosswalk_map,
        n_draws=n_bounds_draws,
        seed=seed,
        blend_inputs=blend_inputs,
    )

    model_variants_included = ["logit"] + (["blended"] if blended_shares is not None else [])

    metadata = {
        "phase": 5,
        "year1": settings.YEAR1,
        "year2": settings.YEAR2,
        "seed": seed,
        "model_variants_included": model_variants_included,
        "primary_bounds_variant": primary_variant,
        "n_bounds_draws": n_bounds_draws,
        "eligibles_2024": eligibles_2024,
        "eligibles_2025": actuals.eligibles_total(penetration_2025_df),
        "terminated_plan_2024_enrollment_dropped_from_share_2024_basis": terminated_count_2024,
        "trend_baseline": trend_diagnostics,
        "suppressed_both_years_plan_count": len(suppressed_both_years),
        "best_naive": best_naive_name,
        "assumptions": [
            (
                "share_2024/enrollment_2024 (per 2025 plan_key) is the crosswalk-mapped 2024 "
                "actual, WITHOUT redistributing terminated (no-2025-successor) plans' share -- "
                "consistent with choice_model/predict.py's NO_SUCCESSOR_BUCKET treatment (dropped, "
                "not pushed onto any specific surviving plan or the outside option). Consequently "
                "sum(share_2024 over per_plan rows) == 1 - (terminated 2024 share), not exactly 1; "
                "see metadata.terminated_plan_2024_enrollment_dropped_from_share_2024_basis."
            ),
            (
                "By contrast, the no_change/trend NAIVE BASELINE PREDICTIONS themselves DO "
                "redistribute terminated-plan share proportionally across every surviving plan + "
                "outside (a deliberate, different, and documented modeling choice for those two "
                "baselines specifically -- see backtest/baselines.py module docstring) -- both "
                "no_change_shares and trend_shares individually sum to 1.0."
            ),
            (
                "trend's 2023 share denominator uses the 2024 eligibles total as a proxy (this "
                "pipeline never ingests a March 2023 penetration/eligibles file, only CPSC "
                "enrollment) -- county-wide MA-eligible population growth between March 2023 and "
                "March 2024 is assumed negligible for this one-year, single-county window."
            ),
            (
                "trend's 2023->2024 plan identity is matched by literal contract_id-plan_id "
                "equality (no CMS 2023->2024 crosswalk file is used in this pipeline); a plan "
                "that changed IDs between 2023 and 2024 is conservatively treated as \"new in "
                "2024\" for trend purposes (2023 share 0.0), the same conservative default "
                "choice_model/predict.py uses for any crosswalk-unmapped key."
            ),
            (
                "CMS-suppressed enrollment cells (<=10, privacy) are imputed to 5 throughout -- "
                "the same convention used in archetypes/plan_priors.py and "
                "choice_model/plan_attributes.py."
            ),
            (
                "best_naive is the single naive baseline (among those computed this run) with the "
                "LOWER weighted_mae; beats_naive[variant] is the explicit rule "
                "weighted_mae(variant) < weighted_mae(best_naive) AND directional_accuracy(variant) "
                ">= directional_accuracy(best_naive) -- computed, never hand-set. beats_naive is "
                "False (not True) whenever either side's directional_accuracy is unavailable "
                "(None, i.e. no evaluable plans), and None for a model variant that wasn't "
                "computed this run (e.g. blended, before make personas has run)."
            ),
            (
                "bounds are Monte Carlo p10/p50/p90 for metadata.primary_bounds_variant only "
                "(blended when available, else logit) -- not computed for every variant."
            ),
            (
                "directional_accuracy is computed over PLAN rows only (excludes the outside "
                "option), and excludes plans CMS-suppressed in BOTH 2024 and 2025 (no reliable "
                "actual-shift signal either year) and plans with exactly zero predicted AND "
                "actual shift."
            ),
        ],
    }

    summary = {
        "weighted_mae": weighted_mae,
        "outside_share_error": outside_share_error,
        "directional_accuracy": directional_accuracy,
        "best_naive": {
            "selected": best_naive_name,
            "weighted_mae": {name: weighted_mae[name] for name in NAIVE_VARIANT_NAMES},
        },
        "beats_naive": beats_naive,
    }

    return {
        "metadata": metadata,
        "per_plan": per_plan,
        "summary": summary,
        "bounds": bounds_result,
    }


# --- file hashing / provenance -------------------------------------------------------


def _artifact_hashes() -> dict[str, str]:
    candidates = [
        settings.PROCESSED_DIR / "archetypes.json",
        settings.PROCESSED_DIR / f"plans_{settings.YEAR1}.json",
        settings.PROCESSED_DIR / f"plans_{settings.YEAR2}.json",
        settings.PROCESSED_DIR / "coefficients.json",
        settings.PROCESSED_DIR / "y2_predictions.json",
        settings.PROCESSED_DIR / "personas.json",
        settings.INTERIM_DIR / "plan_crosswalk_2024_2025.parquet",
        settings.INTERIM_DIR / "cpsc_2024_03.parquet",
        settings.INTERIM_DIR / "cpsc_2025_03.parquet",
        settings.INTERIM_DIR / "cpsc_2023_03.parquet",
        settings.INTERIM_DIR / "penetration_2024_03.parquet",
        settings.INTERIM_DIR / "penetration_2025_03.parquet",
    ]
    return {path.name: sha256_of_file(path) for path in candidates if path.exists()}


# --- I/O + orchestration --------------------------------------------------------------


def build(output_dir: Path | None = None, n_bounds_draws: int = bounds.N_DRAWS_DEFAULT, attempt_trend: bool = True) -> dict:
    """Runs the full backtest against the real committed data files and
    writes ``backtest_result.json``. Returns the same dict as ``run_backtest``
    (with ``metadata.generated_from`` added, computed after the run so it
    can include artifacts -- like a freshly-downloaded cpsc_2023_03.parquet
    -- that only exist once the trend-baseline attempt has run)."""
    inputs = _load_real_inputs()

    result = run_backtest(
        archetypes=inputs["archetypes"],
        plans_2024=inputs["plans_2024"],
        plans_2025=inputs["plans_2025"],
        coefficients=inputs["coefficients"],
        crosswalk_map=inputs["crosswalk_map"],
        cpsc_2024_df=inputs["cpsc_2024_df"],
        cpsc_2025_df=inputs["cpsc_2025_df"],
        penetration_2024_df=inputs["penetration_2024_df"],
        penetration_2025_df=inputs["penetration_2025_df"],
        y2_predictions=inputs["y2_predictions"],
        personas=inputs["personas"],
        n_bounds_draws=n_bounds_draws,
        attempt_trend=attempt_trend,
    )
    result["metadata"]["generated_from"] = _artifact_hashes()

    BacktestResult.model_validate(result)  # fail loudly on a malformed artifact

    dest_dir = output_dir if output_dir is not None else settings.PROCESSED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / RESULT_FILENAME).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    return result


if __name__ == "__main__":
    out = build()
    summary = out["summary"]
    meta = out["metadata"]
    print(f"{RESULT_FILENAME}: {len(out['per_plan'])} per-plan rows, model_variants_included={meta['model_variants_included']}")
    print(f"trend_baseline available={meta['trend_baseline'].get('available')}")
    print("weighted_mae (pp, plan-level, outside excluded):")
    for variant, value in summary["weighted_mae"].items():
        display = f"{value * 100:.4f}pp" if value is not None else "n/a"
        print(f"  {variant:<10} {display}")
    print("directional_accuracy:")
    for variant, value in summary["directional_accuracy"].items():
        display = f"{value * 100:.2f}%" if value is not None else "n/a"
        print(f"  {variant:<10} {display}")
    print(f"best_naive: {summary['best_naive']['selected']}")
    print(f"beats_naive: {summary['beats_naive']}")
