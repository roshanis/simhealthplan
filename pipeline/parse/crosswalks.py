"""Parse: SSA<->FIPS county crosswalk (NBER) + CMS MA plan crosswalk (2024->2025).

SSA<->FIPS: ``data/raw_cache/crosswalks/ssa_fips_state_county_2025.csv``
(NBER, comma-delimited). Normalized to ``fips, county, state, ssa``.

Plan crosswalk: ``data/raw_cache/crosswalks/plan-crosswalk-2025.zip`` ->
``PlanCrosswalk2024_10012024.txt`` (CMS, tab-delimited, latin-1 encoded —
verified: contains non-UTF-8 bytes in some plan names). Maps each Year-1
(previous) plan to its Year-2 (current) plan and a CMS STATUS string. We
normalize STATUS to a compact ``disposition``:

    "Renewal Plan" (+ "with SAR"/"with SAE" sub-variants)
        -> "renewed"      if (contract, plan) unchanged
        -> "renumbered"   if (contract, plan) changed
    "Consolidated Renewal Plan"       -> "consolidated"
    "Terminated/Non-renewed Contract" -> "terminated"
    "New Plan" / "Initial Contract"   -> "new"

The file carries no Segment ID; empirically 100% of Maricopa landscape plans
use segment "0", so old_segment_id/new_segment_id are set to "0" (documented
assumption, not fabricated per-row data).
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from config.settings import settings

DATASET = "crosswalks"

PLAN_CROSSWALK_COLUMNS = [
    "old_contract_id",
    "old_plan_id",
    "old_segment_id",
    "old_plan_name",
    "new_contract_id",
    "new_plan_id",
    "new_segment_id",
    "new_plan_name",
    "disposition",
]

_RENEWAL_STATUSES = {"Renewal Plan", "Renewal Plan with SAR", "Renewal Plan with SAE"}
_STATUS_MAP = {
    "Consolidated Renewal Plan": "consolidated",
    "Terminated/Non-renewed Contract": "terminated",
    "New Plan": "new",
    "Initial Contract": "new",
}

DEFAULT_SEGMENT_ID = "0"


# --- SSA <-> FIPS -------------------------------------------------------------


def parse_ssa_fips(raw_bytes: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw_bytes), dtype=str, keep_default_na=False)
    out = pd.DataFrame(
        {
            "fips": df["fipscounty"].str.zfill(5),
            "county": df["countyname_fips"],
            "state": df["state"],
            "ssa": df["ssa_code"].str.zfill(5),
        }
    )
    return out


def _find_cached_ssa_fips_csv() -> Path:
    matches = sorted((settings.RAW_CACHE_DIR / DATASET).glob("ssa_fips_state_county_*.csv"))
    if not matches:
        raise FileNotFoundError(
            f"No cached ssa_fips_state_county_*.csv in {settings.RAW_CACHE_DIR / DATASET}. "
            "Run `uv run python -m ingest.crosswalks` first."
        )
    return matches[0]


# --- CMS plan crosswalk --------------------------------------------------------


def _normalize_disposition(status: str, old_key: tuple[str, str], new_key: tuple[str, str]) -> str:
    if status in _RENEWAL_STATUSES:
        return "renewed" if old_key == new_key else "renumbered"
    return _STATUS_MAP.get(status, status.lower())


def parse_plan_crosswalk(raw_bytes: bytes) -> pd.DataFrame:
    text = raw_bytes.decode("latin-1")
    df = pd.read_csv(io.StringIO(text), sep="\t", dtype=str, keep_default_na=False)

    old_key = list(zip(df["PREVIOUS_CONTRACT_ID"], df["PREVIOUS_PLAN_ID"]))
    new_key = list(zip(df["CURRENT_CONTRACT_ID"], df["CURRENT_PLAN_ID"]))
    disposition = [
        _normalize_disposition(status, ok, nk)
        for status, ok, nk in zip(df["STATUS"], old_key, new_key)
    ]

    out = pd.DataFrame(
        {
            "old_contract_id": df["PREVIOUS_CONTRACT_ID"],
            "old_plan_id": df["PREVIOUS_PLAN_ID"],
            "old_segment_id": DEFAULT_SEGMENT_ID,
            "old_plan_name": df["PREVIOUS_PLAN_NAME"],
            "new_contract_id": df["CURRENT_CONTRACT_ID"],
            "new_plan_id": df["CURRENT_PLAN_ID"],
            "new_segment_id": DEFAULT_SEGMENT_ID,
            "new_plan_name": df["CURRENT_PLAN_NAME"],
            "disposition": disposition,
        }
    )
    return out[PLAN_CROSSWALK_COLUMNS]


def filter_to_plans(df: pd.DataFrame, plan_keys: set[tuple[str, str]]) -> pd.DataFrame:
    mask = list(zip(df["old_contract_id"], df["old_plan_id"]))
    keep = [k in plan_keys for k in mask]
    return df[keep].reset_index(drop=True)


def resolution_rate(df: pd.DataFrame, plan_keys: set[tuple[str, str]]) -> float:
    resolved = set(zip(df["old_contract_id"], df["old_plan_id"])) & plan_keys
    if not plan_keys:
        return 0.0
    return len(resolved) / len(plan_keys)


def _read_plan_crosswalk_bytes_from_zip(zip_path: Path) -> bytes:
    with zipfile.ZipFile(zip_path) as z:
        matches = [n for n in z.namelist() if re.search(r"PlanCrosswalk.*\.txt$", n)]
        if not matches:
            raise RuntimeError(f"No plan crosswalk .txt found inside {zip_path}")
        return z.read(matches[0])


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    ssa_fips_raw = _find_cached_ssa_fips_csv().read_bytes()
    ssa_fips_df = parse_ssa_fips(ssa_fips_raw)

    plan_zip = settings.RAW_CACHE_DIR / DATASET / "plan-crosswalk-2025.zip"
    plan_raw = _read_plan_crosswalk_bytes_from_zip(plan_zip)
    plan_df_full = parse_plan_crosswalk(plan_raw)

    landscape_2024_path = settings.INTERIM_DIR / "landscape_2024.parquet"
    if landscape_2024_path.exists():
        landscape_2024 = pd.read_parquet(landscape_2024_path)
        maricopa_keys = set(zip(landscape_2024["contract_id"], landscape_2024["plan_id"]))
        plan_df = filter_to_plans(plan_df_full, maricopa_keys)
    else:
        plan_df = plan_df_full

    settings.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    ssa_fips_df.to_parquet(settings.INTERIM_DIR / "ssa_fips_crosswalk.parquet", index=False)
    plan_df.to_parquet(settings.INTERIM_DIR / "plan_crosswalk_2024_2025.parquet", index=False)
    return ssa_fips_df, plan_df


if __name__ == "__main__":
    ssa_fips_df, plan_df = run()
    print(f"ssa_fips_crosswalk: {len(ssa_fips_df)} counties")
    print(f"plan_crosswalk_2024_2025: {len(plan_df)} Maricopa Year-1 plans")
    print(plan_df["disposition"].value_counts())
