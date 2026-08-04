"""Ingest: CMS Doctors and Clinicians National Downloadable File + Census ZCTA->county crosswalk.

Two artifacts:

1. The Doctors and Clinicians National Downloadable File ("DAC") from CMS's
   Provider Data Catalog -- one row per clinician x enrollment record x
   group x practice address, nationwide (~4M rows). This is CMS's public
   physician roster (NPI, specialty, group practice, address). Note what it
   is NOT: CMS publishes no dataset linking physicians to Medicare Advantage
   plan networks, so this feeds descriptive physician-supply context only,
   never the choice model (see parse/physicians.py).

   The Provider Data Catalog's dataset pages are a JS application (no
   scrapeable ``<a href>`` file links), so unlike the cms.gov landing pages
   this repo scrapes elsewhere, the file URL is resolved from the catalog's
   metastore API -- the documented, stable machine interface for exactly
   this purpose. Only the dataset identifier is pinned; the file URL
   (which embeds a content hash + timestamp that changes every release)
   is always resolved at runtime.

2. The Census 2020 ZCTA->county relationship file (plain text, one row per
   ZCTA x county intersection with land-area overlap). The DAC file carries
   no county field -- only ZIP -- so Maricopa filtering assigns each ZCTA
   to its max-land-area county and keeps FIPS 04013 (a documented ZIP~=ZCTA
   proxy, same spirit as the pipeline's other documented proxies).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from config.settings import settings
from ingest.base import DownloadRecord, download_file, fetch_page, find_links

DATASET = "physicians"

# --- CMS Doctors and Clinicians (Provider Data Catalog) -----------------------
# https://data.cms.gov/provider-data/dataset/mj5m-pzi6 -- "National
# Downloadable File" in the Doctors and Clinicians section. The identifier is
# the catalog's stable dataset ID; the CSV's actual URL rotates per release.
DAC_DATASET_ID = "mj5m-pzi6"
DAC_DATASET_PAGE_URL = f"https://data.cms.gov/provider-data/dataset/{DAC_DATASET_ID}"
DAC_METASTORE_URL = (
    f"https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/{DAC_DATASET_ID}"
)
DAC_FILENAME = "DAC_NationalDownloadableFile.csv"

# --- Census ZCTA->county relationship file ------------------------------------
# Plain directory index (no JS), scraped like every other landing page here.
ZCTA_COUNTY_LANDING_PAGE = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
ZCTA_COUNTY_LINK_PATTERN = r"tab20_zcta520_county20_natl\.txt$"


def resolve_dac_url(metastore_json: str | None = None, client: httpx.Client | None = None) -> str:
    """The current DAC CSV downloadURL from the catalog's metastore API.

    Defensive against the two distribution shapes the DKAN-based catalog has
    used (``distribution[].data.downloadURL`` vs ``distribution[].downloadURL``);
    picks the first distribution exposing a downloadURL.
    """
    raw = metastore_json if metastore_json is not None else fetch_page(DAC_METASTORE_URL, client=client)
    item = json.loads(raw)
    for dist in item.get("distribution", []):
        url = dist.get("downloadURL") or dist.get("data", {}).get("downloadURL")
        if url:
            return url
    raise RuntimeError(
        f"No distribution downloadURL in metastore item for dataset {DAC_DATASET_ID!r} "
        f"({DAC_METASTORE_URL}). The Provider Data Catalog API may have changed shape — "
        f"inspect that URL's JSON and update resolve_dac_url."
    )


def ingest_dac(client: httpx.Client | None = None, force: bool = False) -> DownloadRecord:
    url = resolve_dac_url(client=client)
    # Fixed dest name: the source filename embeds a per-release hash, which
    # would defeat the cache-first skip on re-runs.
    dest = settings.RAW_CACHE_DIR / DATASET / DAC_FILENAME
    return download_file(
        dataset=DATASET,
        url=url,
        dest=dest,
        source_page_url=DAC_DATASET_PAGE_URL,
        client=client,
        force=force,
        notes="Doctors and Clinicians National Downloadable File (Provider Data Catalog)",
    )


def resolve_zcta_county_url(
    html: str | None = None, client: httpx.Client | None = None
) -> tuple[str, str]:
    html = html if html is not None else fetch_page(ZCTA_COUNTY_LANDING_PAGE, client=client)
    links = find_links(html, ZCTA_COUNTY_LANDING_PAGE, ZCTA_COUNTY_LINK_PATTERN)
    if not links:
        raise RuntimeError(
            f"No ZCTA->county relationship file matching {ZCTA_COUNTY_LINK_PATTERN!r} on "
            f"{ZCTA_COUNTY_LANDING_PAGE}. Census may have reorganized the rel2020 directory — "
            "browse it for the current zcta520_county20 national file."
        )
    return links[0]


def ingest_zcta_county(client: httpx.Client | None = None, force: bool = False) -> DownloadRecord:
    url, text = resolve_zcta_county_url(client=client)
    dest = settings.RAW_CACHE_DIR / DATASET / Path(url).name
    return download_file(
        dataset=DATASET,
        url=url,
        dest=dest,
        source_page_url=ZCTA_COUNTY_LANDING_PAGE,
        client=client,
        force=force,
        notes=text,
    )


def ingest_all(client: httpx.Client | None = None, force: bool = False) -> list[DownloadRecord]:
    return [ingest_zcta_county(client=client, force=force), ingest_dac(client=client, force=force)]


if __name__ == "__main__":
    for record in ingest_all():
        print(record)
