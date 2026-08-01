"""Parse: PBP Benefits targeted extract, 2024 (Q1) + 2025 -> 5 flags + MOOP per Maricopa plan.

Source zips (large, national, ~90 files each):
``data/raw_cache/pbp_benefits/{2024_q1,2025}__pbp-benefits-*.zip``. Per the
brief, we filter to Maricopa contract/plan IDs (from parse/landscape.py)
before doing any heavy parsing — each individual benefit file has 100-950
columns and hundreds of thousands of national rows.

Encoding note: these files contain stray non-UTF-8 bytes (observed: 0x96 in
free-text fields) and occasional embedded characters that break pandas' C
CSV parser under its default MINIMAL quoting. Every read uses
``encoding="latin-1"`` and ``quoting=csv.QUOTE_NONE`` (there is no quoting
in these files at all — fields never contain the tab delimiter).

Extracted per plan (contract_id, plan_id, segment_id):
  has_comprehensive_dental <- pbp_b16_dental.txt, section b16b ("Comprehensive
                               Dental": extractions/endo/perio/prosthodontics,
                               as opposed to b16a "Preventive Dental").
  has_vision                <- pbp_b17_eye_exams_wear.txt, section b17a (eye
                               exams) OR b17b (eyewear) -- either counts as
                               "has vision benefit".
  has_hearing_aids          <- pbp_b18_hearing_exams_aids.txt, section b18b
                               ("Hearing Aids", as opposed to b18a "Hearing
                               Exams" alone).
  has_otc_or_flex           <- pbp_b13_other_services.txt,
                               pbp_b13b_bendesc_otc ("OTC Items" sub-benefit).
                               CMS does not code a separate "flex card"
                               benefit; plans that market a flex/OTC card
                               administer it through this same OTC allowance
                               field, so it's used as the proxy for both.
  moop_inn                   <- NOT published anywhere in the PBP benefits
                               extract for either year (verified: every
                               column header across all ~90 files in both
                               zips was grepped for "moop"/"oop" - none
                               exists for MA in-network MOOP). Sourced
                               instead from parse/landscape.py's
                               already-validated moop_inn column. The
                               "cross-check vs landscape" in the brief is
                               therefore a no-op by construction, documented
                               here rather than silently skipped.

KNOWN SCHEMA BREAK (dental only, verified between the two zips): CY2024's
pbp_b16_dental.txt has one summary flag ``pbp_b16b_bendesc_yn`` for the
whole comprehensive-dental section. CY2025's version of the same file drops
that summary flag entirely and only publishes per-sub-benefit Y/N fields
(``pbp_b16b_maxenr_pv_yn``, ``pbp_b16b_coins_ov_yn``, ...). ``extract_dental``
handles both: it uses the summary flag when the column exists, and falls
back to "covered if ANY b16b_*_yn field == '1'" otherwise. Sanity check
against real data: both encodings produce a near-identical covered fraction
for Maricopa plans (~84-85%), so the heuristic is not silently making up an
answer.

Any plan where a flag can't be resolved by either file falls back to
``pipeline/parse/manual_benefit_fallback.csv``.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from config.settings import settings

DATASET = "pbp_benefits"
PLAN_KEY_COLS = ["pbp_a_hnumber", "pbp_a_plan_identifier", "segment_id"]

MANUAL_FALLBACK_PATH = Path(__file__).parent / "manual_benefit_fallback.csv"

OUTPUT_COLUMNS = [
    "contract_id",
    "plan_id",
    "segment_id",
    "has_comprehensive_dental",
    "has_vision",
    "has_hearing_aids",
    "has_otc_or_flex",
    "moop_inn",
    "source",
    "year",
]

FLAG_COLUMNS = ["has_comprehensive_dental", "has_vision", "has_hearing_aids", "has_otc_or_flex"]


def _read_pbp_tsv(raw_bytes: bytes) -> pd.DataFrame:
    text = raw_bytes.decode("latin-1")
    return pd.read_csv(io.StringIO(text), sep="\t", dtype=str, quoting=csv.QUOTE_NONE)


def _filter_to_plans(df: pd.DataFrame, plan_keys: set[tuple[str, str, str]]) -> pd.DataFrame:
    keys = list(zip(df["pbp_a_hnumber"], df["pbp_a_plan_identifier"], df["segment_id"]))
    mask = [k in plan_keys for k in keys]
    return df[mask].reset_index(drop=True)


def _to_key_bool_map(df: pd.DataFrame, value_series: pd.Series) -> dict[tuple[str, str, str], bool]:
    keys = list(zip(df["pbp_a_hnumber"], df["pbp_a_plan_identifier"], df["segment_id"]))
    return dict(zip(keys, value_series))


def extract_dental(raw_bytes: bytes, plan_keys: set[tuple[str, str, str]]) -> dict[tuple[str, str, str], bool]:
    df = _read_pbp_tsv(raw_bytes)
    df = _filter_to_plans(df, plan_keys)
    if "pbp_b16b_bendesc_yn" in df.columns:
        covered = df["pbp_b16b_bendesc_yn"] == "1"
    else:
        subfield_cols = [c for c in df.columns if c.startswith("pbp_b16b_") and c.endswith("_yn")]
        covered = df[subfield_cols].eq("1").any(axis=1) if subfield_cols else pd.Series(False, index=df.index)
    return _to_key_bool_map(df, covered)


def extract_vision(raw_bytes: bytes, plan_keys: set[tuple[str, str, str]]) -> dict[tuple[str, str, str], bool]:
    df = _read_pbp_tsv(raw_bytes)
    df = _filter_to_plans(df, plan_keys)
    covered = (df.get("pbp_b17a_bendesc_yn") == "1") | (df.get("pbp_b17b_bendesc_yn") == "1")
    return _to_key_bool_map(df, covered)


def extract_hearing(raw_bytes: bytes, plan_keys: set[tuple[str, str, str]]) -> dict[tuple[str, str, str], bool]:
    df = _read_pbp_tsv(raw_bytes)
    df = _filter_to_plans(df, plan_keys)
    covered = df.get("pbp_b18b_bendesc_yn") == "1"
    return _to_key_bool_map(df, covered)


def extract_otc(raw_bytes: bytes, plan_keys: set[tuple[str, str, str]]) -> dict[tuple[str, str, str], bool]:
    df = _read_pbp_tsv(raw_bytes)
    df = _filter_to_plans(df, plan_keys)
    covered = df.get("pbp_b13b_bendesc_otc") == "1"
    return _to_key_bool_map(df, covered)


def load_manual_fallback(path: Path = MANUAL_FALLBACK_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "year", "contract_id", "plan_id", "segment_id",
                "has_comprehensive_dental", "has_vision", "has_hearing_aids",
                "has_otc_or_flex", "source_note",
            ]
        )
    df = pd.read_csv(path, dtype={"contract_id": str, "plan_id": str, "segment_id": str})
    for col in FLAG_COLUMNS:
        if col in df.columns:
            df[col] = df[col].map({"True": True, "False": False, True: True, False: False})
    return df


def assemble(
    plan_keys: set[tuple[str, str, str]],
    dental: dict[tuple[str, str, str], bool],
    vision: dict[tuple[str, str, str], bool],
    hearing: dict[tuple[str, str, str], bool],
    otc: dict[tuple[str, str, str], bool],
    moop: dict[tuple[str, str, str], float],
    year: int,
) -> pd.DataFrame:
    records = []
    for key in sorted(plan_keys):
        contract_id, plan_id, segment_id = key
        records.append(
            {
                "contract_id": contract_id,
                "plan_id": plan_id,
                "segment_id": segment_id,
                "has_comprehensive_dental": dental.get(key),
                "has_vision": vision.get(key),
                "has_hearing_aids": hearing.get(key),
                "has_otc_or_flex": otc.get(key),
                "moop_inn": moop.get(key),
                "source": "auto",
                "year": year,
            }
        )
    return pd.DataFrame.from_records(records, columns=OUTPUT_COLUMNS)


def apply_manual_fallback(df: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    fallback_by_key = {
        (str(r["contract_id"]), str(r["plan_id"]), str(r["segment_id"])): r
        for _, r in fallback[fallback["year"] == df["year"].iloc[0]].iterrows()
    } if len(df) and "year" in fallback.columns and len(fallback) else {}

    for idx, row in df.iterrows():
        key = (row["contract_id"], row["plan_id"], row["segment_id"])
        missing_flags = [c for c in FLAG_COLUMNS if pd.isna(row[c])]
        if missing_flags and key in fallback_by_key:
            fb = fallback_by_key[key]
            for col in FLAG_COLUMNS:
                if pd.isna(df.at[idx, col]) and col in fb and pd.notna(fb[col]):
                    df.at[idx, col] = fb[col]
            df.at[idx, "source"] = "manual_fallback"
    return df


def coverage_rate(df: pd.DataFrame) -> float:
    if len(df) == 0:
        return 1.0
    fully_covered = df[FLAG_COLUMNS].notna().all(axis=1)
    return fully_covered.mean()


def uncovered_plans(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    fully_covered = df[FLAG_COLUMNS].notna().all(axis=1)
    missing = df[~fully_covered]
    return list(zip(missing["contract_id"], missing["plan_id"], missing["segment_id"]))


# --- Orchestration -------------------------------------------------------------


def _find_zip_entry(zip_path: Path, filename: str) -> bytes:
    with zipfile.ZipFile(zip_path) as z:
        matches = [n for n in z.namelist() if n == filename or n.endswith("/" + filename)]
        if not matches:
            raise RuntimeError(f"{filename!r} not found in {zip_path}")
        return z.read(matches[0])


def build_year(zip_path: Path, landscape_df: pd.DataFrame, year: int) -> pd.DataFrame:
    plan_keys = set(zip(landscape_df["contract_id"], landscape_df["plan_id"], landscape_df["segment_id"]))
    moop = {
        (r["contract_id"], r["plan_id"], r["segment_id"]): r["moop_inn"]
        for _, r in landscape_df.iterrows()
    }

    dental = extract_dental(_find_zip_entry(zip_path, "pbp_b16_dental.txt"), plan_keys)
    vision = extract_vision(_find_zip_entry(zip_path, "pbp_b17_eye_exams_wear.txt"), plan_keys)
    hearing = extract_hearing(_find_zip_entry(zip_path, "pbp_b18_hearing_exams_aids.txt"), plan_keys)
    otc = extract_otc(_find_zip_entry(zip_path, "pbp_b13_other_services.txt"), plan_keys)

    df = assemble(plan_keys, dental, vision, hearing, otc, moop, year)
    fallback = load_manual_fallback()
    df = apply_manual_fallback(df, fallback)
    return df


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    landscape_2024 = pd.read_parquet(settings.INTERIM_DIR / "landscape_2024.parquet")
    landscape_2025 = pd.read_parquet(settings.INTERIM_DIR / "landscape_2025.parquet")

    zip_2024 = settings.RAW_CACHE_DIR / DATASET / "2024_q1__pbp-benefits-2024-quarter-1.zip"
    zip_2025 = settings.RAW_CACHE_DIR / DATASET / "2025__pbp-benefits-2025.zip"

    df_2024 = build_year(zip_2024, landscape_2024, 2024)
    df_2025 = build_year(zip_2025, landscape_2025, 2025)

    settings.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    df_2024.to_parquet(settings.INTERIM_DIR / "benefits_2024.parquet", index=False)
    df_2025.to_parquet(settings.INTERIM_DIR / "benefits_2025.parquet", index=False)
    return df_2024, df_2025


if __name__ == "__main__":
    d24, d25 = run()
    for year, df in ((2024, d24), (2025, d25)):
        rate = coverage_rate(df)
        print(f"benefits_{year}: {len(df)} plans, coverage={rate:.1%}")
        if rate < 1.0:
            print(f"  uncovered: {uncovered_plans(df)}")
