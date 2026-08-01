"""Ingest: PBP Benefits targeted extract, 2024 (earliest available quarter) + 2025.

These are large national files (~25MB zipped each); parse/benefits.py filters
to Maricopa contract/plan IDs before doing any heavy parsing.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from config.settings import settings
from ingest.base import DownloadRecord, download_file, fetch_page, find_links

DATASET = "pbp_benefits"

LANDING_PAGE_2024 = (
    "https://www.cms.gov/data-research/statistics-trends-and-reports/"
    "medicare-advantagepart-d-contract-and-enrollment-data/benefits-data/2024-pbp-benefits-q1"
)
LANDING_PAGE_2025 = (
    "https://www.cms.gov/data-research/statistics-trends-and-reports/"
    "medicare-advantagepart-d-contract-and-enrollment-data/benefits-data/2025-pbp-benefits"
)

LINK_PATTERN = r"pbp-benefits-\d{4}(-quarter-\d)?\.zip(-\d+)?"


def resolve_download_url(
    landing_page_url: str, html: str | None = None, client: httpx.Client | None = None
) -> tuple[str, str]:
    html = html if html is not None else fetch_page(landing_page_url, client=client)
    links = find_links(html, landing_page_url, LINK_PATTERN)
    if not links:
        raise RuntimeError(
            f"No PBP benefits zip link found on {landing_page_url}. CMS may "
            "have renamed the page — search cms.gov for 'PBP Benefits'."
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
        timeout=600.0,
    )


def ingest_all(client: httpx.Client | None = None, force: bool = False) -> list[DownloadRecord]:
    return [
        ingest(LANDING_PAGE_2024, "2024_q1", client=client, force=force),
        ingest(LANDING_PAGE_2025, "2025", client=client, force=force),
    ]


if __name__ == "__main__":
    for record in ingest_all():
        print(record)
