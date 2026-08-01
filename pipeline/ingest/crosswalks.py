"""Ingest: SSA<->FIPS county crosswalk (NBER) + CMS MA plan crosswalk (2024->2025)."""

from __future__ import annotations

from pathlib import Path

import httpx

from config.settings import settings
from ingest.base import DownloadRecord, download_file, fetch_page, find_links

DATASET = "crosswalks"

# --- SSA <-> FIPS county crosswalk (NBER) -------------------------------------
# NBER serves this as a plain Apache directory index (no JS rendering needed).
SSA_FIPS_LANDING_PAGE = "https://data.nber.org/ssa-fips-state-county-crosswalk/2025/"
# Match the plain CSV, not the .dta/.sas7bdat/.zip siblings or the CBSA variant.
SSA_FIPS_LINK_PATTERN = r"^ssa_fips_state_county_\d{4}\.csv$"


def resolve_ssa_fips_url(
    html: str | None = None, client: httpx.Client | None = None
) -> tuple[str, str]:
    html = html if html is not None else fetch_page(SSA_FIPS_LANDING_PAGE, client=client)
    links = find_links(html, SSA_FIPS_LANDING_PAGE, SSA_FIPS_LINK_PATTERN)
    if not links:
        raise RuntimeError(
            f"No ssa_fips_state_county_YYYY.csv link found on {SSA_FIPS_LANDING_PAGE}. "
            "NBER may have reorganized the directory — browse "
            "https://data.nber.org/ssa-fips-state-county-crosswalk/ for the current year."
        )
    return links[0]


def ingest_ssa_fips(client: httpx.Client | None = None, force: bool = False) -> DownloadRecord:
    url, text = resolve_ssa_fips_url(client=client)
    dest = settings.RAW_CACHE_DIR / DATASET / Path(url).name
    return download_file(
        dataset=DATASET,
        url=url,
        dest=dest,
        source_page_url=SSA_FIPS_LANDING_PAGE,
        client=client,
        force=force,
        notes=text,
    )


# --- CMS MA plan crosswalk (year-over-year plan renumbering/terminations) ----
PLAN_CROSSWALK_LANDING_PAGE = (
    "https://www.cms.gov/data-research/statistics-trends-and-reports/"
    "medicare-advantagepart-d-contract-and-enrollment-data/plan-crosswalks/2025-part-cd-plan-crosswalk"
)
PLAN_CROSSWALK_LINK_PATTERN = r"plan-crosswalk-2025\.zip(-\d+)?"


def resolve_plan_crosswalk_url(
    html: str | None = None, client: httpx.Client | None = None
) -> tuple[str, str]:
    html = html if html is not None else fetch_page(PLAN_CROSSWALK_LANDING_PAGE, client=client)
    links = find_links(html, PLAN_CROSSWALK_LANDING_PAGE, PLAN_CROSSWALK_LINK_PATTERN)
    if not links:
        raise RuntimeError(
            f"No plan crosswalk zip link found on {PLAN_CROSSWALK_LANDING_PAGE}. "
            "CMS may have renamed the page — search cms.gov for 'Part C&D Plan Crosswalk'."
        )
    return links[0]


def ingest_plan_crosswalk(client: httpx.Client | None = None, force: bool = False) -> DownloadRecord:
    url, text = resolve_plan_crosswalk_url(client=client)
    dest = settings.RAW_CACHE_DIR / DATASET / Path(url).name
    return download_file(
        dataset=DATASET,
        url=url,
        dest=dest,
        source_page_url=PLAN_CROSSWALK_LANDING_PAGE,
        client=client,
        force=force,
        notes=text,
    )


def ingest_all(client: httpx.Client | None = None, force: bool = False) -> list[DownloadRecord]:
    return [
        ingest_ssa_fips(client=client, force=force),
        ingest_plan_crosswalk(client=client, force=force),
    ]


if __name__ == "__main__":
    for record in ingest_all():
        print(record)
