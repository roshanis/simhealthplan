"""Shared download framework for CMS / NBER / Census data ingestion.

Design goals (see pipeline build spec, Phase 1):
  - CMS.gov blocks generic HTTP clients but allows a browser User-Agent.
    ``BROWSER_USER_AGENT`` / ``DEFAULT_HEADERS`` must be sent on every
    cms.gov request.
  - Never hard-code file URLs: landing pages are scraped for hrefs matching
    a dataset-specific pattern via :func:`find_links`.
  - Downloads are cache-first (skip if the destination file already
    exists) and idempotent across repeated runs.
  - Every downloaded artifact is logged to a JSON manifest
    (``data/raw_cache/manifest.json`` by default) with the source landing
    page URL, the resolved file URL, sha256, byte size, and a UTC
    timestamp.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import settings

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {"User-Agent": BROWSER_USER_AGENT}

DEFAULT_MANIFEST_PATH = settings.RAW_CACHE_DIR / "manifest.json"


def _is_retryable_http_status(exc: BaseException) -> bool:
    """Retry on transient (5xx) server errors, not on 4xx client errors."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def _retrying():
    """3 attempts, exponential backoff — per the ingestion spec."""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=(
            retry_if_exception_type(httpx.TransportError)
            | retry_if_exception(_is_retryable_http_status)
        ),
        reraise=True,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _make_client(timeout: float) -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=timeout, headers=DEFAULT_HEADERS)


@_retrying()
def fetch_page(url: str, client: httpx.Client | None = None, timeout: float = 30.0) -> str:
    """GET a landing page's HTML with the browser User-Agent CMS.gov requires."""
    owns_client = client is None
    c = client or _make_client(timeout)
    try:
        r = c.get(url)
        r.raise_for_status()
        return r.text
    finally:
        if owns_client:
            c.close()


def find_links(html: str, base_url: str, pattern: str) -> list[tuple[str, str]]:
    """Scrape ``<a href>`` elements whose href matches ``pattern`` (regex, case-insensitive).

    Returns ``(absolute_url, link_text)`` tuples, in document order. Relative
    hrefs are resolved against ``base_url``. This is how every dataset
    resolves its actual file URL — no URL is ever hard-coded.
    """
    soup = BeautifulSoup(html, "html.parser")
    regex = re.compile(pattern, re.IGNORECASE)
    results: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if regex.search(href):
            results.append((urljoin(base_url, href), a.get_text(strip=True)))
    return results


def sha256_of_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_manifest(manifest: dict, path: Path = DEFAULT_MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


@dataclass
class DownloadRecord:
    dataset: str
    filename: str
    source_page_url: str | None
    resolved_file_url: str
    sha256: str
    bytes: int
    downloaded_at: str
    skipped_cached: bool = False
    notes: str | None = None


@_retrying()
def _stream_download(client: httpx.Client, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.replace(dest)


# File URLs are resolved by scraping landing pages (find_links), so constrain
# where a scraped href may actually send a download: a compromised or malformed
# source page must not be able to redirect the pipeline to an arbitrary host.
ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "cms.gov",
        "www.cms.gov",
        "data.cms.gov",
        "www2.census.gov",
        "data.census.gov",
        "api.census.gov",
        "data.nber.org",
    }
)


class DisallowedHostError(ValueError):
    """Raised when a resolved download URL points outside ALLOWED_DOWNLOAD_HOSTS."""


def _check_host_allowed(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_DOWNLOAD_HOSTS:
        raise DisallowedHostError(
            f"Refusing to download from {host!r} ({url}): not in "
            f"ALLOWED_DOWNLOAD_HOSTS. If a data source legitimately moved, "
            f"add its host to pipeline/ingest/base.py explicitly."
        )


def download_file(
    dataset: str,
    url: str,
    dest: Path,
    source_page_url: str | None = None,
    client: httpx.Client | None = None,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    force: bool = False,
    notes: str | None = None,
    timeout: float = 300.0,
) -> DownloadRecord:
    """Cache-first streaming download with manifest logging.

    If ``dest`` already exists and ``force`` is False, no network request is
    made — the existing file is re-hashed and re-recorded (idempotent
    re-runs, e.g. rerunning ``make ingest`` after a partial prior run).
    Network downloads are restricted to ALLOWED_DOWNLOAD_HOSTS; the guard
    sits on the network path only, so cache-hit reruns never re-check.
    """
    manifest = load_manifest(manifest_path)
    ds_entries = manifest.setdefault(dataset, {})

    if dest.exists() and not force:
        sha = sha256_of_file(dest)
        prior = ds_entries.get(dest.name, {})
        record = DownloadRecord(
            dataset=dataset,
            filename=dest.name,
            source_page_url=source_page_url or prior.get("source_page_url"),
            resolved_file_url=url,
            sha256=sha,
            bytes=dest.stat().st_size,
            downloaded_at=prior.get("downloaded_at", _now_iso()),
            skipped_cached=True,
            notes=notes or prior.get("notes"),
        )
        ds_entries[dest.name] = asdict(record)
        save_manifest(manifest, manifest_path)
        return record

    _check_host_allowed(url)
    owns_client = client is None
    c = client or _make_client(timeout)
    try:
        _stream_download(c, url, dest)
    finally:
        if owns_client:
            c.close()

    record = DownloadRecord(
        dataset=dataset,
        filename=dest.name,
        source_page_url=source_page_url,
        resolved_file_url=url,
        sha256=sha256_of_file(dest),
        bytes=dest.stat().st_size,
        downloaded_at=_now_iso(),
        skipped_cached=False,
        notes=notes,
    )
    ds_entries[dest.name] = asdict(record)
    save_manifest(manifest, manifest_path)
    return record
