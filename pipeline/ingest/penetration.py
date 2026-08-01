"""Ingest: MA State/County Penetration, March 2024 + March 2025."""

from __future__ import annotations

from pathlib import Path

import httpx

from config.settings import settings
from ingest.base import DownloadRecord, download_file, fetch_page, find_links

DATASET = "penetration"

LANDING_PAGE_2024_03 = (
    "https://www.cms.gov/data-research/statistics-trends-and-reports/"
    "medicare-advantagepart-d-contract-and-enrollment-data/ma-state/"
    "county-penetration/ma-state/county-penetration-2024-03"
)
LANDING_PAGE_2025_03 = (
    "https://www.cms.gov/data-research/statistics-trends-and-reports/"
    "medicare-advantagepart-d-contract-and-enrollment-data/ma-state/"
    "county-penetration/ma-state/county-penetration-2025-03"
)

LINK_PATTERN = r"county-penetration-march-\d{4}\.zip(-\d+)?"


def resolve_download_url(
    landing_page_url: str, html: str | None = None, client: httpx.Client | None = None
) -> tuple[str, str]:
    html = html if html is not None else fetch_page(landing_page_url, client=client)
    links = find_links(html, landing_page_url, LINK_PATTERN)
    if not links:
        raise RuntimeError(
            f"No penetration zip link found on {landing_page_url}. CMS may "
            "have renamed the page — search cms.gov for 'MA State/County Penetration'."
        )
    return links[0]


def ingest(
    landing_page_url: str,
    label: str,
    client: httpx.Client | None = None,
    force: bool = False,
) -> DownloadRecord:
    url, text = resolve_download_url(landing_page_url, client=client)
    filename = f"{label}__{Path(url).name}"
    dest = settings.RAW_CACHE_DIR / DATASET / filename
    return download_file(
        dataset=DATASET,
        url=url,
        dest=dest,
        source_page_url=landing_page_url,
        client=client,
        force=force,
        notes=text,
    )


def ingest_all(client: httpx.Client | None = None, force: bool = False) -> list[DownloadRecord]:
    return [
        ingest(LANDING_PAGE_2024_03, "2024_03", client=client, force=force),
        ingest(LANDING_PAGE_2025_03, "2025_03", client=client, force=force),
    ]


if __name__ == "__main__":
    for record in ingest_all():
        print(record)
