"""Parse: MA & Part D Landscape files (CY2024 + CY2025) -> unified Maricopa schema.

Source archive: ``data/raw_cache/landscape/cy2006-cy2025-landscape-files.zip``.
CMS does not publish standalone CY2024/CY2025 zips on the Part D landing
page (verified 2026-07-31) — only this single consolidated "CY2006-CY2025
Landscape Files" archive, which nests a nother zip per multi-year block.

KNOWN SCHEMA BREAK (CMS's CY2025 Landscape Format Memo), verified against
the real files:
  - CY2024 ships as 3 separate CSVs in a "csv version" folder:
      * an MA file (non-SNP MA plans; one consolidated Part C+D premium,
        no Part C/Part D split, no SNP Type),
      * an SNP file (D/C/I-SNP MA plans; same shape, plus SNP Type, but
        *no MOOP column at all*),
      * a Plan Premium Report, keyed by (Contract ID, Plan ID, Segment ID)
        + County, which has the actual Part C / Part D premium split.
        A small number of MA/SNP plans (observed: $0-premium "Medicare
        Give Back" plans with no Part D) have no matching row in this
        report at all.
  - CY2025 ships as ONE consolidated CSV with renamed, richer columns that
    already include the Part C/Part D split and SNP Type inline.

Both are normalized to:
    contract_id, plan_id, segment_id, state, county, org_name, plan_name,
    plan_type, snp_type, premium_part_c, premium_part_d, deductible,
    moop_inn, star_rating, year

``star_rating`` is kept as a string column (not float) on purpose: CMS
reports non-numeric sentinels ("Not enough data available", "Plan too new
to be measured") for a meaningful fraction of plans, and the Phase 1
acceptance criterion requires star_rating to be non-null for every landscape
row — collapsing those sentinels to NaN would violate that while a plain
float column can't represent them at all.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from config.settings import settings

DATASET = "landscape"
ARCHIVE_NAME = "cy2006-cy2025-landscape-files.zip"

# Anchored on a path boundary so this can't accidentally match the parent
# folder name "CY2022-CY2024_Landscape_Files/", which contains the substring
# "CY2024_Landscape_Files" as part of its own name.
INNER_2024_ZIP_PATTERN = r"(^|/)CY2024_Landscape_Files_Final.*\.zip$"
INNER_2024_MA_PATTERN = r"csv version/CY2024_Landscape_MA_.*\.csv$"
INNER_2024_SNP_PATTERN = r"csv version/CY2024_Landscape_SNP_.*\.csv$"
INNER_2024_PREMIUM_PATTERN = r"csv version/CY2024_Plan_Premium_Report_.*\.csv$"

# Anchored on a path boundary ("^" or "/") so this can't accidentally match
# the parent folder name "CY2022-CY2024_Landscape_Files/", which contains
# "CY2024_Landscape_Files" as a substring of its *own* name.
INNER_2025_ZIP_PATTERN = r"(^|/)CY2025_Landscape_.*\.zip$"
INNER_2025_CSV_PATTERN = r"(^|/)CY2025_Landscape_.*\.csv$"

EXPECTED_COLUMNS = [
    "contract_id",
    "plan_id",
    "segment_id",
    "state",
    "county",
    "org_name",
    "plan_name",
    "plan_type",
    "snp_type",
    "premium_part_c",
    "premium_part_d",
    "deductible",
    "moop_inn",
    "star_rating",
    "year",
]

NO_SNP_SENTINEL = "Not Applicable"


def money_to_float(raw: str | None) -> float | None:
    """'$5,100.00 ' -> 5100.0; '' / None -> None."""
    if raw is None:
        return None
    s = raw.strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _find_entry(names: list[str], pattern: str) -> str:
    regex = re.compile(pattern)
    matches = [n for n in names if regex.search(n)]
    if not matches:
        raise RuntimeError(
            f"No zip entry matching {pattern!r} found among {len(names)} entries. "
            "CMS may have renamed the archive's internal layout — inspect the "
            "zip and update the pattern in parse/landscape.py."
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"Ambiguous pattern {pattern!r} matched {len(matches)} entries: {matches!r}. "
            "Tighten the pattern in parse/landscape.py."
        )
    return matches[0]


def extract_2024_csvs(archive_path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(archive_path) as outer:
        inner_name = _find_entry(outer.namelist(), INNER_2024_ZIP_PATTERN)
        inner_bytes = outer.read(inner_name)
    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
        names = inner.namelist()
        ma_name = _find_entry(names, INNER_2024_MA_PATTERN)
        snp_name = _find_entry(names, INNER_2024_SNP_PATTERN)
        premium_name = _find_entry(names, INNER_2024_PREMIUM_PATTERN)
        return {
            "ma": inner.read(ma_name),
            "snp": inner.read(snp_name),
            "premium": inner.read(premium_name),
        }


def extract_2025_csv(archive_path: Path) -> bytes:
    with zipfile.ZipFile(archive_path) as outer:
        inner_name = _find_entry(outer.namelist(), INNER_2025_ZIP_PATTERN)
        inner_bytes = outer.read(inner_name)
    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
        csv_name = _find_entry(inner.namelist(), INNER_2025_CSV_PATTERN)
        return inner.read(csv_name)


def _read_csv(raw_bytes: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw_bytes), encoding="utf-8-sig", dtype=str, keep_default_na=False)


def parse_2024(ma_bytes: bytes, snp_bytes: bytes, premium_bytes: bytes) -> pd.DataFrame:
    ma = _read_csv(ma_bytes)
    ma = ma[(ma["State"] == "Arizona") & (ma["County"] == settings.COUNTY_NAME)].copy()
    ma["snp_type"] = NO_SNP_SENTINEL
    ma["moop_inn"] = ma["In-network MOOP Amount **"].map(money_to_float)

    snp = _read_csv(snp_bytes)
    snp = snp[(snp["State"] == "Arizona") & (snp["County"] == settings.COUNTY_NAME)].copy()
    snp["snp_type"] = snp["Special Needs Plan Type"]
    snp["moop_inn"] = None  # CY2024 SNP file publishes no MOOP column at all.
    snp = snp.rename(
        columns={"Monthly Consolidated Premium* (Includes Part C + D)": "Monthly Consolidated Premium (Includes Part C + D)"}
    )

    common_cols = [
        "State",
        "County",
        "Organization Name",
        "Plan Name",
        "Type of Medicare Health Plan",
        "Monthly Consolidated Premium (Includes Part C + D)",
        "Annual Drug Deductible",
        "Contract ID",
        "Plan ID",
        "Segment ID",
        "2024 Overall Star Rating",
        "snp_type",
        "moop_inn",
    ]
    base = pd.concat([ma[common_cols], snp[common_cols]], ignore_index=True)

    premium = _read_csv(premium_bytes)
    premium = premium[(premium["State"] == "Arizona") & (premium["County"] == settings.COUNTY_NAME)].copy()
    premium["premium_part_c"] = premium["Part C Premium"].map(money_to_float)
    premium["premium_part_d"] = premium["Part D Total Premium"].map(money_to_float)
    premium_lookup = premium.set_index(["Contract ID", "Plan ID", "Segment ID"])[
        ["premium_part_c", "premium_part_d"]
    ]

    base["consolidated_premium"] = base["Monthly Consolidated Premium (Includes Part C + D)"].map(money_to_float)
    joined = base.join(
        premium_lookup, on=["Contract ID", "Plan ID", "Segment ID"], how="left"
    )
    # Fallback for plans absent from the Plan Premium Report (observed: $0
    # "Medicare Give Back" / no-Part-D plans): attribute the whole
    # consolidated premium to Part C, $0 to Part D.
    missing = joined["premium_part_c"].isna()
    joined.loc[missing, "premium_part_c"] = joined.loc[missing, "consolidated_premium"]
    joined.loc[missing, "premium_part_d"] = joined.loc[missing, "premium_part_d"].fillna(0.0)

    out = pd.DataFrame(
        {
            "contract_id": joined["Contract ID"].astype(str),
            "plan_id": joined["Plan ID"].astype(str),
            "segment_id": joined["Segment ID"].astype(str),
            "state": "AZ",
            "county": settings.COUNTY_NAME,
            "org_name": joined["Organization Name"],
            "plan_name": joined["Plan Name"],
            "plan_type": joined["Type of Medicare Health Plan"].str.rstrip(" *"),
            "snp_type": joined["snp_type"].replace("", NO_SNP_SENTINEL),
            "premium_part_c": joined["premium_part_c"].astype(float),
            "premium_part_d": joined["premium_part_d"].astype(float),
            "deductible": joined["Annual Drug Deductible"].map(money_to_float),
            "moop_inn": joined["moop_inn"].astype(float),
            "star_rating": joined["2024 Overall Star Rating"],
            "year": 2024,
        }
    )
    out["year"] = out["year"].astype("int64")
    out = out.drop_duplicates(subset=["contract_id", "plan_id", "segment_id"]).reset_index(drop=True)
    return out[EXPECTED_COLUMNS]


def parse_2025(csv_bytes: bytes) -> pd.DataFrame:
    df = _read_csv(csv_bytes)
    df = df[(df["State Name"] == "Arizona") & (df["County Name"] == settings.COUNTY_NAME)].copy()

    out = pd.DataFrame(
        {
            "contract_id": df["Contract ID"].astype(str),
            "plan_id": df["Plan ID"].astype(str),
            "segment_id": df["Segment ID"].astype(str),
            "state": "AZ",
            "county": settings.COUNTY_NAME,
            "org_name": df["Organization Marketing Name"],
            "plan_name": df["Plan Name"],
            "plan_type": df["Plan Type"],
            "snp_type": df["SNP Type"].replace("", NO_SNP_SENTINEL),
            "premium_part_c": df["Part C Premium"].map(money_to_float),
            "premium_part_d": df["Part D Total Premium"].map(money_to_float),
            "deductible": df["Annual Part D Deductible Amount"].map(money_to_float),
            "moop_inn": df["In-Network Maximum Out-of-Pocket (MOOP) Amount"].map(money_to_float),
            "star_rating": df["Overall Star Rating"],
            "year": 2025,
        }
    )
    # MA-only plans with no Part D benefit report "Not Applicable" rather
    # than a numeric premium (verified: e.g. Contract R7220-001, "Part D
    # Coverage Indicator" == "No"). Treat "not applicable" as "$0 charged
    # for a benefit that doesn't exist" so premium_part_c/premium_part_d
    # stay non-null for every plan, matching the CY2024 fallback rule.
    out["premium_part_c"] = out["premium_part_c"].fillna(0.0)
    out["premium_part_d"] = out["premium_part_d"].fillna(0.0)
    out["year"] = out["year"].astype("int64")
    out = out.drop_duplicates(subset=["contract_id", "plan_id", "segment_id"]).reset_index(drop=True)
    return out[EXPECTED_COLUMNS]


def run(archive_path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    archive_path = archive_path or (settings.RAW_CACHE_DIR / DATASET / ARCHIVE_NAME)
    csvs_2024 = extract_2024_csvs(archive_path)
    df2024 = parse_2024(csvs_2024["ma"], csvs_2024["snp"], csvs_2024["premium"])

    csv_2025 = extract_2025_csv(archive_path)
    df2025 = parse_2025(csv_2025)

    settings.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    df2024.to_parquet(settings.INTERIM_DIR / "landscape_2024.parquet", index=False)
    df2025.to_parquet(settings.INTERIM_DIR / "landscape_2025.parquet", index=False)
    return df2024, df2025


if __name__ == "__main__":
    d24, d25 = run()
    print(f"landscape_2024: {len(d24)} Maricopa rows")
    print(f"landscape_2025: {len(d25)} Maricopa rows")
