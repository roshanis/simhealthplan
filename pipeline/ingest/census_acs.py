"""Ingest: Census ACS 5-year (2018-2022 vintage) tables for Maricopa County (04013).

PRIMARY method (no API key required, per 2026-07-31 amendment to the Phase 1
brief): Census's ACS Summary File "table-based" flat files, served as plain
HTTP off www2.census.gov (verified browsable and non-bot-blocking):

    https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/
        data/5YRData/acsdt5y2022-<table>.dat        (pipe-delimited data)
        documentation/ACS20225YR_Table_Shells.txt   (variable code -> label)

Each ``.dat`` is a *national* file — every summary level (nation, state,
county, tract, block group, ...) concatenated into one file with a GEO_ID
column — so these files are large (tens to hundreds of MB). Maricopa
County's row has ``GEO_ID == "0500000US04013"``. Because the files are
national, parse/census_acs.py streams and filters line-by-line rather than
loading the whole file into a DataFrame.

SECONDARY / optional method: api.census.gov requires CENSUS_API_KEY as of
2026-05 (verified: keyless requests 302-redirect to a "Missing Key" page).
``fetch_via_api`` below is available if a key is configured, but the primary
``ingest()`` path never calls it — the live run for this pipeline uses the
keyless flat-file route exclusively.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from config.settings import settings
from ingest.base import DownloadRecord, download_file

DATASET = "acs"

SUMMARY_FILE_BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/"
DATA_DIR_URL = SUMMARY_FILE_BASE + "data/5YRData/"
DOC_DIR_URL = SUMMARY_FILE_BASE + "documentation/"
TABLE_SHELLS_URL = DOC_DIR_URL + "ACS20225YR_Table_Shells.txt"

# B01001 age/sex, B03002 race/ethnicity, C17002 poverty ratio,
# B19037 age of householder x income.
TABLES = ["b01001", "b03002", "c17002", "b19037"]

MARICOPA_GEO_ID = "0500000US04013"


def table_data_url(table: str) -> str:
    return f"{DATA_DIR_URL}acsdt5y2022-{table}.dat"


def ingest(client: httpx.Client | None = None, force: bool = False) -> list[DownloadRecord]:
    records: list[DownloadRecord] = []
    for table in TABLES:
        url = table_data_url(table)
        dest = settings.RAW_CACHE_DIR / DATASET / Path(url).name
        records.append(
            download_file(
                dataset=DATASET,
                url=url,
                dest=dest,
                source_page_url=DATA_DIR_URL,
                client=client,
                force=force,
                notes=(
                    "ACS 5-year 2018-2022 table-based summary file, national "
                    "(all geographies concatenated); filtered to Maricopa "
                    f"({MARICOPA_GEO_ID}) at parse time"
                ),
                timeout=900.0,
            )
        )

    shells_dest = settings.RAW_CACHE_DIR / DATASET / Path(TABLE_SHELLS_URL).name
    records.append(
        download_file(
            dataset=DATASET,
            url=TABLE_SHELLS_URL,
            dest=shells_dest,
            source_page_url=DOC_DIR_URL,
            client=client,
            force=force,
            notes="variable code -> label mapping (Table ID|Line|Indent|Unique ID|Label|Title|Universe|Type)",
        )
    )
    return records


# --- Optional secondary path: api.census.gov (requires CENSUS_API_KEY) -------

API_BASE = "https://api.census.gov/data/2022/acs/acs5"


def fetch_via_api(get_vars: list[str], client: httpx.Client | None = None) -> list[list[str]]:
    """Optional fallback: api.census.gov, gated behind CENSUS_API_KEY.

    Not used by ``ingest()`` above. Kept for cases where a key becomes
    available and a targeted, low-bandwidth pull is preferable to the
    national flat files.
    """
    if not settings.CENSUS_API_KEY:
        raise RuntimeError(
            "CENSUS_API_KEY not configured (pipeline/.env). The primary "
            "ingest() path (keyless www2.census.gov flat files) does not "
            "require this — call ingest() instead."
        )
    params = {
        "get": ",".join(get_vars),
        "for": f"county:{settings.COUNTY_FIPS[2:]}",
        "in": f"state:{settings.COUNTY_FIPS[:2]}",
        "key": settings.CENSUS_API_KEY,
    }
    owns_client = client is None
    c = client or httpx.Client(follow_redirects=True, timeout=30.0)
    try:
        r = c.get(API_BASE, params=params)
        r.raise_for_status()
        return r.json()
    finally:
        if owns_client:
            c.close()


if __name__ == "__main__":
    for record in ingest():
        print(record)
