"""Parse: CMS Doctors and Clinicians roster -> Maricopa physician-supply tables.

Reads two raw_cache/physicians artifacts (see ingest/physicians.py):

* ``DAC_NationalDownloadableFile.csv`` -- one row per clinician x enrollment
  record x group x practice address, nationwide (~4M rows). Streamed in
  chunks; only Arizona rows whose practice ZIP maps to Maricopa County
  survive, so peak memory stays small.
* ``tab20_zcta520_county20_natl.txt`` -- Census 2020 ZCTA->county
  relationship file (pipe-delimited, one row per ZCTA x county
  intersection). Each ZCTA is assigned to its maximum-land-area county;
  practice ZIPs are then treated as ZCTAs (documented ZIP~=ZCTA proxy --
  the DAC file has no county field, and most ZIPs match their ZCTA).

Column-name robustness: CMS has renamed DAC columns across releases (e.g.
``org_nm`` vs ``Facility Name``, ``cty`` vs ``City/Town``). ``_resolve_columns``
maps every known alias onto one canonical schema and fails loudly (listing
the actual header) if a required column can't be found under any alias.

Outputs:
* ``data/interim/physicians_maricopa.parquet`` -- normalized row-level table
  (clinician x group x address, Maricopa only).
* ``data/processed/physicians.json`` -- the aggregated physician-supply
  summary the app exports (unique clinicians, orgs, telehealth share, top
  specialties/organizations).

What this deliberately is NOT: a plan-network table. CMS publishes no
physician<->MA-plan-network linkage, so physician supply is descriptive
context for the report, never a choice-model input.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from config.settings import settings

DATASET = "physicians"

DAC_FILENAME = "DAC_NationalDownloadableFile.csv"
ZCTA_COUNTY_FILENAME = "tab20_zcta520_county20_natl.txt"

CHUNK_ROWS = 250_000

TOP_SPECIALTIES_N = 20
TOP_ORGS_N = 15

# canonical name -> known CMS header aliases (matched case/space/punctuation-
# insensitively via _normalize_header). First alias found wins.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "npi": ("npi",),
    "last_name": ("lst_nm", "provider last name"),
    "first_name": ("frst_nm", "provider first name"),
    "gender": ("gndr",),
    "credential": ("cred",),
    "med_school": ("med_sch", "medical school name"),
    "grad_year": ("grd_yr", "graduation year"),
    "primary_specialty": ("pri_spec", "primary specialty"),
    "all_secondary_specialties": ("sec_spec_all", "all secondary specialties"),
    "telehealth": ("telehlth", "telehealth"),
    "org_name": ("org_nm", "facility name", "org_lgl_nm", "organization legal name"),
    "org_pac_id": ("org_pac_id",),
    "org_members": ("num_org_mem", "number of group practice members"),
    "city": ("cty", "city/town", "city"),
    "state": ("st", "state"),
    "zip": ("zip", "zip code", "zip_code"),
    "address_id": ("adrs_id",),
}

REQUIRED_CANONICAL = ("npi", "primary_specialty", "state", "zip")

INTERIM_COLUMNS = [
    "npi",
    "last_name",
    "first_name",
    "gender",
    "credential",
    "med_school",
    "grad_year",
    "primary_specialty",
    "all_secondary_specialties",
    "telehealth",
    "org_name",
    "org_pac_id",
    "org_members",
    "city",
    "state",
    "zip5",
    "address_id",
]


def _normalize_header(name: str) -> str:
    """Case/space/punctuation-insensitive header key: 'Provider Last Name' ->
    'provider last name', ' City/Town ' -> 'city/town'."""
    return re.sub(r"\s+", " ", name.strip().lower())


def _resolve_columns(header: list[str]) -> dict[str, str]:
    """Actual CSV header -> {canonical: actual_column_name} for every alias
    that resolves. Raises with the real header if a REQUIRED_CANONICAL
    column can't be found under any alias."""
    by_norm = {_normalize_header(col): col for col in header}
    resolved: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            actual = by_norm.get(_normalize_header(alias))
            if actual is not None:
                resolved[canonical] = actual
                break
    missing = [c for c in REQUIRED_CANONICAL if c not in resolved]
    if missing:
        raise RuntimeError(
            f"DAC file is missing required column(s) {missing} under every known alias. "
            f"CMS may have renamed columns again — actual header: {header}. "
            "Add the new name(s) to COLUMN_ALIASES in parse/physicians.py."
        )
    return resolved


# --- ZCTA -> county ------------------------------------------------------------


def parse_zcta_county(raw_bytes: bytes) -> pd.DataFrame:
    """Census relationship file -> one row per ZCTA with its max-land-area
    county: columns ``zcta`` (5-char) and ``county_fips`` (5-char). Ties
    broken by county FIPS ascending for determinism. Rows with a blank ZCTA
    (county area not covered by any ZCTA) are dropped."""
    df = pd.read_csv(
        pd.io.common.BytesIO(raw_bytes),
        sep="|",
        dtype=str,
        keep_default_na=False,
        encoding="latin-1",
    )
    required = ["GEOID_ZCTA5_20", "GEOID_COUNTY_20", "AREALAND_PART"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"ZCTA->county relationship file is missing column(s) {missing}. "
            f"Actual columns: {list(df.columns)}. Census may have changed the "
            "rel2020 layout — update parse_zcta_county."
        )
    df = df[df["GEOID_ZCTA5_20"] != ""].copy()
    df["arealand_part"] = pd.to_numeric(df["AREALAND_PART"], errors="coerce").fillna(0)
    df = df.sort_values(
        ["GEOID_ZCTA5_20", "arealand_part", "GEOID_COUNTY_20"],
        ascending=[True, False, True],
    )
    best = df.drop_duplicates("GEOID_ZCTA5_20", keep="first")
    return pd.DataFrame(
        {
            "zcta": best["GEOID_ZCTA5_20"].str.zfill(5),
            "county_fips": best["GEOID_COUNTY_20"].str.zfill(5),
        }
    ).reset_index(drop=True)


def county_zips(zcta_county: pd.DataFrame, county_fips: str = settings.COUNTY_FIPS) -> set[str]:
    """The set of ZCTAs whose max-land-area county is ``county_fips``."""
    return set(zcta_county.loc[zcta_county["county_fips"] == county_fips, "zcta"])


# --- DAC roster ---------------------------------------------------------------


def _normalize_chunk(chunk: pd.DataFrame, resolved: dict[str, str], keep_zips: set[str]) -> pd.DataFrame:
    """One raw DAC chunk -> canonical-schema rows for the target county:
    state == STATE_ABBREV and 5-digit practice ZIP in ``keep_zips``."""
    state = chunk[resolved["state"]].str.strip().str.upper()
    zip5 = chunk[resolved["zip"]].str.strip().str[:5]
    mask = (state == settings.STATE_ABBREV) & zip5.isin(keep_zips)
    if not mask.any():
        return pd.DataFrame(columns=INTERIM_COLUMNS)

    kept = chunk[mask]
    out = pd.DataFrame(index=kept.index)
    for canonical in INTERIM_COLUMNS:
        if canonical == "zip5":
            out["zip5"] = zip5[mask]
        elif canonical in resolved:
            out[canonical] = kept[resolved[canonical]].astype(str).str.strip()
        else:
            out[canonical] = ""
    return out


def parse_dac(csv_path: Path, keep_zips: set[str], chunk_rows: int = CHUNK_ROWS) -> pd.DataFrame:
    """Stream the national DAC CSV, keeping only the target county's rows.

    Reads everything as string (NPIs, ZIPs, and PAC IDs must never become
    floats) with ``encoding_errors='replace'`` so a stray non-UTF-8 byte in
    a provider name can't kill a 4M-row parse.
    """
    chunks: list[pd.DataFrame] = []
    resolved: dict[str, str] | None = None
    with pd.read_csv(
        csv_path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8",
        encoding_errors="replace",
        chunksize=chunk_rows,
    ) as reader:
        for chunk in reader:
            if resolved is None:
                resolved = _resolve_columns(list(chunk.columns))
            normalized = _normalize_chunk(chunk, resolved, keep_zips)
            if len(normalized):
                chunks.append(normalized)
    if not chunks:
        return pd.DataFrame(columns=INTERIM_COLUMNS)
    return pd.concat(chunks, ignore_index=True)


# --- aggregation ---------------------------------------------------------------


def _per_clinician(df: pd.DataFrame) -> pd.DataFrame:
    """Row-level (clinician x group x address) -> one row per NPI. Specialty
    is each NPI's first non-empty primary_specialty (the DAC repeats it per
    row); telehealth is True if ANY of the clinician's rows says 'Y'."""
    df = df.sort_values(["npi", "primary_specialty"], ascending=[True, False])
    grouped = df.groupby("npi", sort=True)
    return pd.DataFrame(
        {
            "primary_specialty": grouped["primary_specialty"].first(),
            "telehealth": grouped["telehealth"].apply(lambda s: bool((s.str.upper() == "Y").any())),
        }
    ).reset_index()


def build_summary(df: pd.DataFrame) -> dict:
    """Row-level Maricopa table -> the physician-supply summary dict written
    to data/processed/physicians.json. Pure: DataFrame in, plain dict out."""
    clinicians = _per_clinician(df)

    spec_counts = (
        clinicians[clinicians["primary_specialty"] != ""]
        .groupby("primary_specialty")
        .size()
        .sort_values(ascending=False)
    )
    top_specialties = [
        {"specialty": spec, "clinicians": int(count)}
        for spec, count in sorted(
            spec_counts.items(), key=lambda item: (-item[1], item[0])
        )[:TOP_SPECIALTIES_N]
    ]

    with_org = df[df["org_pac_id"] != ""]
    org_clinicians = with_org.groupby("org_pac_id")["npi"].nunique()
    # Display name: the most common org_name spelling per PAC ID (ties by name).
    org_names = (
        with_org[with_org["org_name"] != ""]
        .groupby("org_pac_id")["org_name"]
        .agg(lambda s: s.value_counts().sort_index().sort_values(ascending=False, kind="stable").index[0])
    )
    top_orgs = [
        {
            "org_name": org_names.get(pac_id, pac_id),
            "clinicians": int(count),
        }
        for pac_id, count in sorted(
            org_clinicians.items(), key=lambda item: (-item[1], str(org_names.get(item[0], item[0])))
        )[:TOP_ORGS_N]
    ]

    total_clinicians = int(clinicians["npi"].nunique())
    return {
        "metadata": {
            "source": "CMS Doctors and Clinicians National Downloadable File (Provider Data Catalog)",
            "dataset_id": "mj5m-pzi6",
            "county_fips": settings.COUNTY_FIPS,
            "county_name": settings.COUNTY_NAME,
            "state": settings.STATE_ABBREV,
            "zip_zcta_proxy": True,
            "network_linkage": False,
        },
        "totals": {
            "clinicians": total_clinicians,
            "organizations": int(org_clinicians.shape[0]),
            "practice_locations": int(df.drop_duplicates(["npi", "address_id"]).shape[0]),
            "specialties": int(spec_counts.shape[0]),
            "telehealth_share": (float(clinicians["telehealth"].mean()) if total_clinicians else 0.0),
        },
        "top_specialties": top_specialties,
        "top_organizations": top_orgs,
    }


# --- entry point ---------------------------------------------------------------


def run() -> tuple[pd.DataFrame, dict]:
    raw_dir = settings.RAW_CACHE_DIR / DATASET
    zcta_path = raw_dir / ZCTA_COUNTY_FILENAME
    dac_path = raw_dir / DAC_FILENAME
    for path in (zcta_path, dac_path):
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Run `uv run python -m ingest.physicians` "
                "(or `make ingest`) first."
            )

    zcta_county = parse_zcta_county(zcta_path.read_bytes())
    keep_zips = county_zips(zcta_county)
    df = parse_dac(dac_path, keep_zips)

    settings.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(settings.INTERIM_DIR / "physicians_maricopa.parquet", index=False)

    summary = build_summary(df)
    settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = settings.PROCESSED_DIR / "physicians.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return df, summary


if __name__ == "__main__":
    df, summary = run()
    totals = summary["totals"]
    print(f"physicians_maricopa: {len(df)} rows")
    print(
        f"  {totals['clinicians']:,} clinicians, {totals['organizations']:,} organizations, "
        f"{totals['telehealth_share']:.1%} telehealth"
    )
