"""Canonical per-plan attribute tables for the Phase 3 choice model.

Builds one row per landscape plan (2024: 93 plans, 2025: 94 plans) with a
normalized, cross-year-consistent attribute set:

  * ``plan_type`` -- CMS plan_type strings differ in format year over year:
    2024 uses "Local HMO" / "Local PPO" / "Regional PPO"; 2025 embeds
    POS/SNP markers, e.g. "HMO D-SNP", "HMO-POS C-SNP". ``normalize_plan_type``
    collapses both onto {HMO, PPO, Regional PPO} via substring match (see its
    docstring). SNP status is captured separately by ``snp_type``, which is
    already consistent across years (Not Applicable / Chronic or Disabling
    Condition / Dual-Eligible / Institutional).
  * ``premium_total`` -- premium_part_c + premium_part_d, rounded to cents.
  * ``moop_inn`` -- 29/93 2024 plans have a null in-network MOOP (a CMS
    Landscape-file gap). Imputed via ``impute_moop``: crosswalk-backfill from
    the same *renewed* plan's 2025 MOOP where available (26/29), else the
    normalized-plan-type median MOOP among 2024's known values (3/29, the
    "consolidated"-disposition plans, which the crosswalk explicitly does not
    treat as a 1:1 renewal). ``imputed_moop`` + ``moop_imputation_method``
    record how each plan's MOOP was sourced. 2025 has no MOOP nulls.
  * ``star_rating`` -- CMS shows non-numeric placeholders for new/unrated
    plans ("Not enough data available" / "Plan too new to be measured" in
    2024; same text, different case, in 2025). ``impute_star_ratings`` fills
    these with the normalized-plan-type median star rating among that year's
    known ratings, flagged via ``imputed_star``.
  * The four supplemental-benefit flags from ``benefits_{year}.parquet``.
  * ``enrollment_{year}_{month:02d}`` -- actual CPSC enrollment for that
    plan; CMS-suppressed small cells (privacy) are imputed to 5, matching
    ``archetypes/plan_priors.py``'s ``DEFAULT_SUPPRESSED_ENROLLMENT_IMPUTE``.

Writes ``data/processed/plans_2024.json`` and ``plans_2025.json``: committed,
deterministic artifacts consumed by ``choice_model/calibrate.py`` and (in a
later phase) the Next.js app / TypeScript port. Plans are sorted by
``plan_key`` for stable, byte-identical reruns.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from choice_model.schemas import PlansFile2024, PlansFile2025
from config.settings import settings

# Matches archetypes/plan_priors.py::DEFAULT_SUPPRESSED_ENROLLMENT_IMPUTE --
# CMS suppresses plan/county enrollment cells below a small-cell privacy
# threshold; both phases impute the same fixed placeholder count.
DEFAULT_SUPPRESSED_ENROLLMENT_IMPUTE = 5

# The crosswalk's "renewed" disposition is the only one this pipeline treats
# as a same-plan year-over-year match for MOOP backfill purposes (see module
# docstring: "consolidated"/"renumbered"/"terminated" plans fall back to the
# type-median instead of borrowing a different plan's MOOP).
CROSSWALK_RENEWED_DISPOSITION = "renewed"

CROSSWALK_BACKFILL_METHOD = "crosswalk_backfill"
TYPE_MEDIAN_METHOD = "type_median"


def plan_key(contract_id: str, plan_id: str) -> str:
    return f"{contract_id}-{plan_id}"


def normalize_plan_type(raw: str) -> str:
    """Collapse a raw CMS plan_type string onto {HMO, PPO, Regional PPO}.

    Substring match, most-specific first: "Regional PPO" beats bare "PPO"
    beats bare "HMO", so POS/SNP-suffixed 2025 strings (e.g. "HMO-POS
    D-SNP") still normalize to their base network type.
    """
    if "Regional PPO" in raw:
        return "Regional PPO"
    if "PPO" in raw:
        return "PPO"
    if "HMO" in raw:
        return "HMO"
    raise ValueError(f"unrecognized plan_type: {raw!r}")


def parse_star_rating(raw: str | None) -> float | None:
    """Numeric star rating, or None for a CMS placeholder / missing value."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def impute_star_ratings(df: pd.DataFrame) -> pd.DataFrame:
    """Fill unratable plans' star rating with the normalized-plan-type median.

    ``df`` must have ``plan_type_norm`` and ``star_rating`` (raw CMS string)
    columns. Returns a copy with ``star_rating_value`` (float) and
    ``imputed_star`` (bool) added.
    """
    out = df.copy()
    parsed = out["star_rating"].map(parse_star_rating)

    known_mask = parsed.notna()
    medians = (
        pd.DataFrame({"plan_type_norm": out.loc[known_mask, "plan_type_norm"], "star": parsed[known_mask]})
        .groupby("plan_type_norm")["star"]
        .median()
    )
    overall_median = float(parsed[known_mask].median()) if known_mask.any() else 3.5

    values = []
    imputed = []
    for is_known, p, ptype in zip(known_mask, parsed, out["plan_type_norm"]):
        if is_known:
            values.append(float(p))
            imputed.append(False)
        else:
            values.append(float(medians.get(ptype, overall_median)))
            imputed.append(True)

    out["star_rating_value"] = values
    out["imputed_star"] = imputed
    return out


def impute_moop(
    df: pd.DataFrame,
    crosswalk_df: pd.DataFrame | None = None,
    other_year_landscape_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Fill null ``moop_inn``: crosswalk-backfill first, else type-median.

    ``df`` must have ``contract_id``, ``plan_id``, ``plan_type_norm``,
    ``moop_inn`` columns. ``crosswalk_df`` (old_contract_id/old_plan_id/
    new_contract_id/new_plan_id/disposition) and ``other_year_landscape_df``
    (contract_id/plan_id/moop_inn) are optional -- when omitted, every null
    falls straight to the type-median fallback. Returns a copy with
    ``moop_imputed_value`` (float), ``imputed_moop`` (bool), and
    ``moop_imputation_method`` (str | None) added.
    """
    out = df.copy()
    out["moop_imputed_value"] = out["moop_inn"].astype(float)
    out["imputed_moop"] = out["moop_inn"].isna()
    out["moop_imputation_method"] = None

    null_idx = out.index[out["moop_inn"].isna()]

    if len(null_idx) and crosswalk_df is not None and other_year_landscape_df is not None:
        renewed = crosswalk_df[crosswalk_df["disposition"] == CROSSWALK_RENEWED_DISPOSITION]
        cw_map = {
            (row.old_contract_id, row.old_plan_id): (row.new_contract_id, row.new_plan_id) for row in renewed.itertuples()
        }
        other_moop = other_year_landscape_df.set_index(["contract_id", "plan_id"])["moop_inn"]

        for idx in null_idx:
            key = (out.at[idx, "contract_id"], out.at[idx, "plan_id"])
            new_key = cw_map.get(key)
            if new_key is not None and new_key in other_moop.index:
                val = other_moop.loc[new_key]
                if pd.notna(val):
                    out.at[idx, "moop_imputed_value"] = float(val)
                    out.at[idx, "moop_imputation_method"] = CROSSWALK_BACKFILL_METHOD

    still_null_idx = out.index[out["moop_imputed_value"].isna()]
    if len(still_null_idx):
        # Median is taken over *originally* non-null MOOP values only (not
        # crosswalk-backfilled ones), so the fallback never compounds one
        # imputed value into another plan's median.
        originally_known = out.loc[out["moop_inn"].notna()]
        medians = originally_known.groupby("plan_type_norm")["moop_imputed_value"].median()
        overall_median = float(originally_known["moop_imputed_value"].median())
        for idx in still_null_idx:
            ptype = out.at[idx, "plan_type_norm"]
            fallback = medians.get(ptype, overall_median)
            out.at[idx, "moop_imputed_value"] = float(fallback)
            out.at[idx, "moop_imputation_method"] = TYPE_MEDIAN_METHOD

    return out


def _attach_enrollment(df: pd.DataFrame, cpsc_df: pd.DataFrame, enrollment_col: str) -> pd.DataFrame:
    cpsc = cpsc_df.copy()
    cpsc["plan_key"] = [plan_key(c, p) for c, p in zip(cpsc["contract_id"], cpsc["plan_id"])]
    sub = cpsc[cpsc["plan_key"].isin(df["plan_key"])].copy()

    enrollment = pd.to_numeric(sub["enrollment"], errors="coerce").to_numpy(dtype=float)
    suppressed = sub["suppressed"].astype(bool).to_numpy()
    sub["enrollment_value"] = np.where(suppressed, float(DEFAULT_SUPPRESSED_ENROLLMENT_IMPUTE), enrollment)

    by_plan = sub.groupby("plan_key")["enrollment_value"].sum().reindex(df["plan_key"], fill_value=0.0)

    out = df.copy()
    out[enrollment_col] = by_plan.to_numpy()
    return out


def build_plan_table(
    year: int,
    landscape_df: pd.DataFrame,
    benefits_df: pd.DataFrame,
    cpsc_df: pd.DataFrame,
    crosswalk_df: pd.DataFrame | None = None,
    other_year_landscape_df: pd.DataFrame | None = None,
    enrollment_month: int = 3,
) -> pd.DataFrame:
    """Pure(ish) core: builds the per-plan attribute table for one year.

    No file I/O -- callers pass in already-loaded DataFrames (this keeps the
    logic unit-testable against small synthetic fixtures; ``build`` below
    handles the real-file I/O + JSON serialization). Returns a DataFrame
    sorted by ``plan_key``.
    """
    land = landscape_df.copy()
    land["plan_key"] = [plan_key(c, p) for c, p in zip(land["contract_id"], land["plan_id"])]
    land["plan_type_norm"] = land["plan_type"].map(normalize_plan_type)
    land["is_ppo"] = land["plan_type_norm"].isin(["PPO", "Regional PPO"])
    land["premium_total"] = (land["premium_part_c"] + land["premium_part_d"]).round(2)

    land = impute_moop(land, crosswalk_df, other_year_landscape_df)
    land = impute_star_ratings(land)

    ben = benefits_df.copy()
    ben["plan_key"] = [plan_key(c, p) for c, p in zip(ben["contract_id"], ben["plan_id"])]
    benefit_cols = ["has_comprehensive_dental", "has_vision", "has_hearing_aids", "has_otc_or_flex"]

    merged = land.merge(ben[["plan_key", *benefit_cols]], on="plan_key", how="left")
    for col in benefit_cols:
        merged[col] = merged[col].fillna(False).astype(bool)

    enrollment_col = f"enrollment_{year}_{enrollment_month:02d}"
    merged = _attach_enrollment(merged, cpsc_df, enrollment_col)
    merged["year"] = year

    merged = merged.rename(
        columns={
            "plan_type": "plan_type_raw",
            "plan_type_norm": "plan_type",
            "star_rating": "star_rating_raw",
            "star_rating_value": "star_rating",
            "moop_imputed_value": "moop_inn_final",
        }
    )
    merged["moop_inn"] = merged["moop_inn_final"].round(2)

    keep_cols = [
        "plan_key",
        "contract_id",
        "plan_id",
        "org_name",
        "plan_name",
        "plan_type_raw",
        "plan_type",
        "is_ppo",
        "snp_type",
        "premium_part_c",
        "premium_part_d",
        "premium_total",
        "deductible",
        "moop_inn",
        "imputed_moop",
        "moop_imputation_method",
        "star_rating_raw",
        "star_rating",
        "imputed_star",
        "has_comprehensive_dental",
        "has_vision",
        "has_hearing_aids",
        "has_otc_or_flex",
        enrollment_col,
        "year",
    ]
    return merged[keep_cols].sort_values("plan_key", kind="mergesort").reset_index(drop=True)


def _to_records(table: pd.DataFrame) -> list[dict]:
    records = []
    for row in table.to_dict(orient="records"):
        record = dict(row)
        for key in ("premium_part_c", "premium_part_d", "premium_total", "deductible", "moop_inn", "star_rating"):
            record[key] = float(record[key])
        for key in record:
            if key.startswith("enrollment_"):
                record[key] = float(record[key])
        record["imputed_moop"] = bool(record["imputed_moop"])
        record["imputed_star"] = bool(record["imputed_star"])
        record["is_ppo"] = bool(record["is_ppo"])
        for key in ("has_comprehensive_dental", "has_vision", "has_hearing_aids", "has_otc_or_flex"):
            record[key] = bool(record[key])
        records.append(record)
    return records


def _imputation_notes(table: pd.DataFrame) -> dict:
    moop_method_counts = table["moop_imputation_method"].value_counts(dropna=True).to_dict()
    star_method_counts_raw = table.loc[table["imputed_star"], "plan_type"].value_counts().to_dict()
    return {
        "moop": {
            "null_count_source": int(table["imputed_moop"].sum()),
            "method_counts": {str(k): int(v) for k, v in moop_method_counts.items()},
            "description": (
                "Null in-network MOOP (CMS Landscape-file gap) imputed via "
                "crosswalk-backfill from the same *renewed* plan's other-year "
                "MOOP where available, else the normalized-plan-type median "
                "among this year's known MOOP values."
            ),
        },
        "star_rating": {
            "null_count_source": int(table["imputed_star"].sum()),
            "method_counts_by_plan_type": {str(k): int(v) for k, v in star_method_counts_raw.items()},
            "description": (
                "CMS placeholder star ratings ('Not enough data available' / "
                "'Plan too new to be measured', case differs 2024 vs 2025) "
                "imputed with the normalized-plan-type median star rating "
                "among this year's known ratings."
            ),
        },
    }


def _load_year_inputs(year: int, enrollment_month: int) -> dict[str, pd.DataFrame]:
    return {
        "landscape": pd.read_parquet(settings.INTERIM_DIR / f"landscape_{year}.parquet"),
        "benefits": pd.read_parquet(settings.INTERIM_DIR / f"benefits_{year}.parquet"),
        "cpsc": pd.read_parquet(settings.INTERIM_DIR / f"cpsc_{year}_{enrollment_month:02d}.parquet"),
    }


def build(year: int, other_year: int, enrollment_month: int = 3) -> dict:
    """Build one year's plan JSON dict (metadata + plans) from real interim files.

    ``other_year`` supplies the cross-year landscape used for 2024's MOOP
    crosswalk backfill (2025 has no MOOP nulls, so it's unused when
    ``year == 2025``, but still loaded for the crosswalk-availability check
    to stay symmetric/simple).
    """
    data = _load_year_inputs(year, enrollment_month)
    other_landscape = pd.read_parquet(settings.INTERIM_DIR / f"landscape_{other_year}.parquet")

    crosswalk_path = settings.INTERIM_DIR / "plan_crosswalk_2024_2025.parquet"
    crosswalk_df = pd.read_parquet(crosswalk_path) if crosswalk_path.exists() else None
    # The crosswalk is directional old(2024)->new(2025); only useful for
    # backfilling year 2024 from year 2025.
    if year != min(year, other_year):
        crosswalk_df = None

    table = build_plan_table(
        year,
        data["landscape"],
        data["benefits"],
        data["cpsc"],
        crosswalk_df=crosswalk_df,
        other_year_landscape_df=other_landscape,
        enrollment_month=enrollment_month,
    )

    metadata = {
        "year": year,
        "enrollment_month": enrollment_month,
        "source_files": [
            f"landscape_{year}.parquet",
            f"benefits_{year}.parquet",
            f"cpsc_{year}_{enrollment_month:02d}.parquet",
            *(["plan_crosswalk_2024_2025.parquet", f"landscape_{other_year}.parquet"] if crosswalk_df is not None else []),
        ],
        "plan_count": int(len(table)),
        "plan_type_normalization": {
            "rule": "substring match, most specific first: 'Regional PPO' > 'PPO' > 'HMO'",
            "note": (
                "2024 raw plan_type is 'Local HMO'/'Local PPO'/'Regional PPO'; "
                "2025 embeds POS/SNP markers (e.g. 'HMO D-SNP', 'HMO-POS "
                "C-SNP'). SNP status is captured separately by snp_type, "
                "which is consistent across both years."
            ),
        },
        "imputation_notes": _imputation_notes(table),
    }

    return {"metadata": metadata, "plans": _to_records(table)}


def build_all(output_dir: Path | None = None) -> dict[int, dict]:
    """Build both years' plan JSONs and write them to disk.

    Returns ``{2024: result_2024, 2025: result_2025}``. Writes
    ``plans_2024.json`` / ``plans_2025.json`` deterministically (sorted
    keys, stable plan ordering) to ``output_dir`` (default
    ``settings.PROCESSED_DIR``).
    """
    dest_dir = output_dir if output_dir is not None else settings.PROCESSED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    results: dict[int, dict] = {}
    for year, other_year, model, filename in (
        (settings.YEAR1, settings.YEAR2, PlansFile2024, f"plans_{settings.YEAR1}.json"),
        (settings.YEAR2, settings.YEAR1, PlansFile2025, f"plans_{settings.YEAR2}.json"),
    ):
        result = build(year, other_year, enrollment_month=settings.ENROLLMENT_MONTH)
        model.model_validate(result)  # fail loudly on a malformed artifact
        results[year] = result

        dest = dest_dir / filename
        dest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    return results


if __name__ == "__main__":
    out = build_all()
    for year, result in out.items():
        meta = result["metadata"]
        print(f"plans_{year}.json: {meta['plan_count']} plans")
        moop_notes = meta["imputation_notes"]["moop"]
        if moop_notes["null_count_source"]:
            print(f"  moop imputed: {moop_notes['null_count_source']} ({moop_notes['method_counts']})")
        star_notes = meta["imputation_notes"]["star_rating"]
        if star_notes["null_count_source"]:
            print(f"  star imputed: {star_notes['null_count_source']} ({star_notes['method_counts_by_plan_type']})")
