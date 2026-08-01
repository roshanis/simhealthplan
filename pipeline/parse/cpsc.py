"""Parse: Monthly Enrollment by Contract/Plan/State/County (CPSC), March 2024 + March 2025.

Source zips: ``data/raw_cache/cpsc/<label>__monthly-enrollment-cpsc-march-<year>.zip[-N]``
(the "-N" suffix is CMS's Drupal de-duplication artifact — see ingest/cpsc.py).
Each zip contains a ``CPSC_Enrollment_Info_<year>_<month>.csv`` national file
(~185MB decompressed, ~3M rows: one row per Contract ID x Plan ID x SSA
county). We stream it row-by-row directly out of the zip member (never
materializing the full national file in memory or on disk) and keep only
rows where "FIPS State County Code" == settings.COUNTY_FIPS.

Suppression: verified empirically against the real March 2024 file — cells
with enrollment <= 10 are suppressed with the literal sentinel ``"*"`` (not
blank, not a placeholder number). Parsed to a nullable Int64 `enrollment`
column plus a `suppressed` bool column.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from typing import IO

import pandas as pd

from config.settings import settings

DATASET = "cpsc"
ENROLLMENT_CSV_PATTERN = r"CPSC_Enrollment_Info_.*\.csv$"
SUPPRESSION_SENTINEL = "*"

EXPECTED_COLUMNS = ["contract_id", "plan_id", "fips", "enrollment", "suppressed", "year_month"]


def find_enrollment_entry(namelist: list[str]) -> str:
    regex = re.compile(ENROLLMENT_CSV_PATTERN)
    matches = [n for n in namelist if regex.search(n)]
    if not matches:
        raise RuntimeError(
            f"No entry matching {ENROLLMENT_CSV_PATTERN!r} found among "
            f"{len(namelist)} zip entries. CMS may have renamed the internal "
            "file — inspect the zip and update parse/cpsc.py."
        )
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous CPSC enrollment entry match: {matches!r}")
    return matches[0]


def _parse_enrollment_cell(raw: str) -> tuple[int | None, bool]:
    raw = raw.strip()
    if raw == SUPPRESSION_SENTINEL:
        return None, True
    if not raw:
        return None, True
    try:
        return int(raw), False
    except ValueError:
        return None, True


def parse_enrollment_stream(text_stream: IO[str], fips: str, year_month: str) -> pd.DataFrame:
    reader = csv.DictReader(text_stream)
    records = []
    for row in reader:
        if row.get("FIPS State County Code", "").strip() != fips:
            continue
        value, suppressed = _parse_enrollment_cell(row.get("Enrollment", ""))
        records.append(
            {
                "contract_id": row["Contract Number"].strip(),
                "plan_id": row["Plan ID"].strip(),
                "fips": fips,
                "enrollment": value,
                "suppressed": suppressed,
                "year_month": year_month,
            }
        )
    df = pd.DataFrame.from_records(records, columns=EXPECTED_COLUMNS)
    df["enrollment"] = df["enrollment"].astype("Int64")
    df["suppressed"] = df["suppressed"].astype(bool)
    return df


def parse_enrollment_bytes(raw_bytes: bytes, fips: str, year_month: str) -> pd.DataFrame:
    text_stream = io.StringIO(raw_bytes.decode("utf-8-sig"))
    return parse_enrollment_stream(text_stream, fips, year_month)


def parse_zip(zip_path: Path, fips: str, year_month: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        entry = find_enrollment_entry(z.namelist())
        with z.open(entry) as raw_stream:
            text_stream = io.TextIOWrapper(raw_stream, encoding="utf-8-sig", newline="")
            return parse_enrollment_stream(text_stream, fips, year_month)


def _find_cached_zip(label: str) -> Path:
    matches = sorted((settings.RAW_CACHE_DIR / DATASET).glob(f"{label}__*.zip*"))
    if not matches:
        raise FileNotFoundError(
            f"No cached CPSC zip found for label {label!r} in "
            f"{settings.RAW_CACHE_DIR / DATASET}. Run `uv run python -m ingest.cpsc` first."
        )
    return matches[0]


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    df_2024 = parse_zip(_find_cached_zip("2024_03"), settings.COUNTY_FIPS, "2024-03")
    df_2025 = parse_zip(_find_cached_zip("2025_03"), settings.COUNTY_FIPS, "2025-03")

    settings.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    df_2024.to_parquet(settings.INTERIM_DIR / "cpsc_2024_03.parquet", index=False)
    df_2025.to_parquet(settings.INTERIM_DIR / "cpsc_2025_03.parquet", index=False)
    return df_2024, df_2025


if __name__ == "__main__":
    d24, d25 = run()
    print(f"cpsc_2024_03: {len(d24)} Maricopa rows, total enrollment={d24['enrollment'].sum()}")
    print(f"cpsc_2025_03: {len(d25)} Maricopa rows, total enrollment={d25['enrollment'].sum()}")
