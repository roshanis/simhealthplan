"""Parse: MA State/County Penetration, March 2024 + March 2025.

Source zips: ``data/raw_cache/penetration/<label>__county-penetration-march-<year>.zip``.
Each zip contains one small national CSV (~85KB) with columns:
State Name, County Name, FIPSST, FIPSCNTY, FIPS, SSAST, SSACNTY, SSA,
Eligibles, Enrolled, Penetration.

NOTE / deviation from the Phase 1 brief: the brief anticipated needing the
SSA<->FIPS crosswalk (ingest/crosswalks.py, #6) to join this file, since it
"uses SSA county codes not FIPS". Empirically (verified against both real
files) the file already carries a FIPS column directly, so we key off FIPS
without the crosswalk. However CY2024 zero-pads FIPSST/FIPSCNTY ("04",
"013") while CY2025 does not ("4", "13"), and even the "FIPS" column itself
is inconsistently padded across years — so we reconstruct a canonical
5-digit FIPS as FIPSST.zfill(2) + FIPSCNTY.zfill(3) rather than trusting
that column. The SSA code is reconstructed the same way (SSAST.zfill(2) +
SSACNTY.zfill(3)) and matches the SSA codes seen in the CPSC enrollment
file 1:1 (e.g. Maricopa == "03060" in both), so it's carried through as a
useful join key for later phases even though it isn't required to locate
Maricopa here.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from config.settings import settings

DATASET = "penetration"
EXPECTED_COLUMNS = ["state", "county", "fips", "ssa", "eligibles", "enrolled", "penetration", "year_month"]


def money_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    s = raw.strip().replace(",", "")
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def pct_to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = raw.strip().replace("%", "")
    if not s:
        return None
    try:
        return round(float(s) / 100.0, 6)
    except ValueError:
        return None


def _read_csv(raw_bytes: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw_bytes), encoding="utf-8-sig", dtype=str, keep_default_na=False)


def parse_national(raw_bytes: bytes, year_month: str) -> pd.DataFrame:
    df = _read_csv(raw_bytes)
    fips = df["FIPSST"].str.zfill(2) + df["FIPSCNTY"].str.zfill(3)
    ssa = df["SSAST"].str.zfill(2) + df["SSACNTY"].str.zfill(3)
    out = pd.DataFrame(
        {
            "state": df["State Name"],
            "county": df["County Name"],
            "fips": fips,
            "ssa": ssa,
            "eligibles": df["Eligibles"].map(money_int),
            "enrolled": df["Enrolled"].map(money_int),
            "penetration": df["Penetration"].map(pct_to_float),
            "year_month": year_month,
        }
    )
    out["eligibles"] = out["eligibles"].astype("Int64")
    out["enrolled"] = out["enrolled"].astype("Int64")
    return out[EXPECTED_COLUMNS]


def extract_county(raw_bytes: bytes, fips: str, year_month: str) -> pd.DataFrame:
    national = parse_national(raw_bytes, year_month)
    return national[national["fips"] == fips].reset_index(drop=True)


def _find_cached_zip(label: str) -> Path:
    matches = sorted((settings.RAW_CACHE_DIR / DATASET).glob(f"{label}__*.zip*"))
    if not matches:
        raise FileNotFoundError(
            f"No cached penetration zip found for label {label!r} in "
            f"{settings.RAW_CACHE_DIR / DATASET}. Run `uv run python -m ingest.penetration` first."
        )
    return matches[0]


def _read_csv_from_zip(zip_path: Path) -> bytes:
    import re
    import zipfile

    with zipfile.ZipFile(zip_path) as z:
        matches = [n for n in z.namelist() if re.search(r"State_County_Penetration_MA_.*\.csv$", n)]
        if not matches:
            raise RuntimeError(f"No penetration CSV found inside {zip_path}")
        return z.read(matches[0])


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_2024 = _read_csv_from_zip(_find_cached_zip("2024_03"))
    raw_2025 = _read_csv_from_zip(_find_cached_zip("2025_03"))

    df_2024 = extract_county(raw_2024, settings.COUNTY_FIPS, "2024-03")
    df_2025 = extract_county(raw_2025, settings.COUNTY_FIPS, "2025-03")

    settings.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    df_2024.to_parquet(settings.INTERIM_DIR / "penetration_2024_03.parquet", index=False)
    df_2025.to_parquet(settings.INTERIM_DIR / "penetration_2025_03.parquet", index=False)
    return df_2024, df_2025


if __name__ == "__main__":
    d24, d25 = run()
    print(d24.to_dict(orient="records"))
    print(d25.to_dict(orient="records"))
