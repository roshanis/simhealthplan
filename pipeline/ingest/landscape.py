"""Ingest: MA & Part D Landscape files (CY2024 + CY2025).

Landing page: https://www.cms.gov/medicare/coverage/prescription-drug-coverage

CMS does not publish standalone CY2024/CY2025 landscape files on this page
(verified 2026-07-31) — only a consolidated "CY2006-CY2025 Landscape Files"
archive. We download that single archive once; parse/landscape.py extracts
both plan years from it.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from config.settings import settings
from ingest.base import DownloadRecord, download_file, fetch_page, find_links

DATASET = "landscape"
LANDING_PAGE_URL = "https://www.cms.gov/medicare/coverage/prescription-drug-coverage"
# Matches the consolidated multi-year archive, not the single-year CY2026 file
# or the congressional district reports that live on the same page.
LINK_PATTERN = r"cy2006-cy2025-landscape-files\.zip"


def resolve_download_url(
    html: str | None = None, client: httpx.Client | None = None
) -> tuple[str, str]:
    html = html if html is not None else fetch_page(LANDING_PAGE_URL, client=client)
    links = find_links(html, LANDING_PAGE_URL, LINK_PATTERN)
    if not links:
        raise RuntimeError(
            f"No landscape archive link matching {LINK_PATTERN!r} found on "
            f"{LANDING_PAGE_URL}. CMS may have renamed/moved the page — "
            "search cms.gov for 'Landscape file' and update LINK_PATTERN."
        )
    return links[0]


def ingest(client: httpx.Client | None = None, force: bool = False) -> DownloadRecord:
    url, text = resolve_download_url(client=client)
    dest = settings.RAW_CACHE_DIR / DATASET / Path(url).name
    return download_file(
        dataset=DATASET,
        url=url,
        dest=dest,
        source_page_url=LANDING_PAGE_URL,
        client=client,
        force=force,
        notes=text,
    )


if __name__ == "__main__":
    record = ingest()
    print(record)
