"""Ingest: MCBS Survey File PUF (latest available year) + its documentation.

The nominal landing page
(https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/mcbs-public-use-file)
redirects to https://data.cms.gov/medicare-current-beneficiary-survey-mcbs,
a client-side-rendered React SPA — httpx sees ~3KB of empty shell HTML, no
scrapeable hrefs. data.cms.gov publishes the same catalog the SPA reads from
as a static DCAT JSON feed at https://data.cms.gov/data.json; we resolve the
Survey File PUF's latest-year distribution from that feed instead. This is
the documented deviation from the "scrape the landing page" pattern used by
every other CMS dataset in this pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from config.settings import settings
from ingest.base import DownloadRecord, DEFAULT_HEADERS, download_file

DATASET = "mcbs"

LANDING_PAGE_URL = (
    "https://www.cms.gov/research-statistics-data-and-systems/"
    "downloadable-public-use-files/mcbs-public-use-file"
)
CATALOG_URL = "https://data.cms.gov/data.json"
SURVEY_FILE_TITLE = "Medicare Current Beneficiary Survey - Survey File"


@dataclass
class McbsSurveyFileResolution:
    data_url: str
    codebook_url: str | None
    title: str
    temporal: str | None


def _fetch_catalog(client: httpx.Client | None = None) -> dict:
    owns_client = client is None
    c = client or httpx.Client(follow_redirects=True, timeout=60.0, headers=DEFAULT_HEADERS)
    try:
        r = c.get(CATALOG_URL)
        r.raise_for_status()
        return r.json()
    finally:
        if owns_client:
            c.close()


def resolve_survey_file(
    catalog: dict | None = None, client: httpx.Client | None = None
) -> McbsSurveyFileResolution:
    catalog = catalog if catalog is not None else _fetch_catalog(client=client)
    datasets = catalog.get("dataset", [])
    matches = [d for d in datasets if d.get("title", "").strip() == SURVEY_FILE_TITLE]
    if not matches:
        raise RuntimeError(
            f"No dataset titled {SURVEY_FILE_TITLE!r} found in {CATALOG_URL}. "
            "CMS/data.cms.gov may have renamed it — search data.cms.gov for 'MCBS Survey File'."
        )
    record = matches[0]
    distributions = record.get("distribution", [])
    if not distributions:
        raise RuntimeError(f"{SURVEY_FILE_TITLE!r} dataset has no distributions in the catalog.")
    # Distributions are listed most-recent-first in the CMS catalog; take the first.
    latest = distributions[0]
    return McbsSurveyFileResolution(
        data_url=latest["downloadURL"],
        codebook_url=record.get("describedBy"),
        title=latest.get("title", SURVEY_FILE_TITLE),
        temporal=latest.get("temporal"),
    )


def ingest(client: httpx.Client | None = None, force: bool = False) -> list[DownloadRecord]:
    resolution = resolve_survey_file(client=client)
    records = []

    data_dest = settings.RAW_CACHE_DIR / DATASET / Path(resolution.data_url).name
    records.append(
        download_file(
            dataset=DATASET,
            url=resolution.data_url,
            dest=data_dest,
            source_page_url=LANDING_PAGE_URL,
            client=client,
            force=force,
            notes=f"resolved via {CATALOG_URL} (SPA landing page not scrapeable); {resolution.title}",
            timeout=300.0,
        )
    )

    if resolution.codebook_url:
        codebook_dest = settings.RAW_CACHE_DIR / DATASET / Path(resolution.codebook_url).name
        records.append(
            download_file(
                dataset=DATASET,
                url=resolution.codebook_url,
                dest=codebook_dest,
                source_page_url=LANDING_PAGE_URL,
                client=client,
                force=force,
                notes=f"codebook/data-user's-guide bundle, resolved via {CATALOG_URL}",
            )
        )

    return records


if __name__ == "__main__":
    for record in ingest():
        print(record)
