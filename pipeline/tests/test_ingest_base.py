"""Tests for pipeline/ingest/base.py — the shared download framework.

TDD: written before ingest/base.py exists. All network calls are faked via
httpx.MockTransport so these tests are hermetic (no real network access).
"""

from __future__ import annotations

import json

import httpx
import pytest

from ingest.base import (
    BROWSER_USER_AGENT,
    DownloadRecord,
    download_file,
    find_links,
    load_manifest,
    save_manifest,
    sha256_of_file,
)

SAMPLE_HTML = """
<html><body>
<a href="/files/zip/monthly-enrollment-cpsc-march-2025.zip-0">Monthly Enrollment - March 2025</a>
<a href="/files/other/not-a-match.txt">Not a match</a>
<a href="https://www.cms.gov/files/zip/other-file.zip">Other zip</a>
</body></html>
"""


def test_browser_user_agent_is_a_real_chrome_ua():
    assert "Chrome" in BROWSER_USER_AGENT
    assert "Mozilla/5.0" in BROWSER_USER_AGENT


def test_find_links_matches_zip_pattern_and_resolves_relative_urls():
    links = find_links(SAMPLE_HTML, "https://www.cms.gov/some/page", r"\.zip")
    hrefs = [href for href, _text in links]
    assert "https://www.cms.gov/files/zip/monthly-enrollment-cpsc-march-2025.zip-0" in hrefs
    assert "https://www.cms.gov/files/zip/other-file.zip" in hrefs
    assert not any("not-a-match" in h for h in hrefs)


def test_find_links_handles_cms_drupal_suffix():
    # CMS appends "-0" etc to duplicate filenames; the pattern must still match
    # because it's applied before the trailing suffix in the href, not the
    # extension boundary.
    links = find_links(SAMPLE_HTML, "https://www.cms.gov/some/page", r"\.zip(-\d+)?$")
    hrefs = [href for href, _text in links]
    assert any(h.endswith("march-2025.zip-0") for h in hrefs)


def test_sha256_of_file(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_bytes(b"hello world")
    digest = sha256_of_file(f)
    # known sha256("hello world")
    assert digest == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_manifest_round_trip(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    data = {"dataset_a": {"file.zip": {"sha256": "abc", "bytes": 10}}}
    save_manifest(data, manifest_path)
    loaded = load_manifest(manifest_path)
    assert loaded == data


def test_load_manifest_missing_file_returns_empty_dict(tmp_path):
    assert load_manifest(tmp_path / "nope.json") == {}


def _mock_client(body: bytes, status_code: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body)

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_download_file_streams_and_records_manifest(tmp_path):
    dest = tmp_path / "raw_cache" / "dataset_a" / "file.zip"
    manifest_path = tmp_path / "manifest.json"
    client = _mock_client(b"fake zip contents")

    record = download_file(
        dataset="dataset_a",
        url="https://www.cms.gov/files/zip/file.zip",
        dest=dest,
        source_page_url="https://www.cms.gov/landing",
        client=client,
        manifest_path=manifest_path,
    )

    assert dest.exists()
    assert dest.read_bytes() == b"fake zip contents"
    assert isinstance(record, DownloadRecord)
    assert record.sha256 == sha256_of_file(dest)
    assert record.bytes == len(b"fake zip contents")
    assert record.skipped_cached is False

    manifest = load_manifest(manifest_path)
    assert manifest["dataset_a"]["file.zip"]["resolved_file_url"] == "https://www.cms.gov/files/zip/file.zip"
    assert manifest["dataset_a"]["file.zip"]["source_page_url"] == "https://www.cms.gov/landing"


def test_download_file_is_cache_first_and_skips_existing(tmp_path):
    dest = tmp_path / "raw_cache" / "dataset_a" / "file.zip"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"already cached content")
    manifest_path = tmp_path / "manifest.json"

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"should not be fetched")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    record = download_file(
        dataset="dataset_a",
        url="https://www.cms.gov/files/zip/file.zip",
        dest=dest,
        client=client,
        manifest_path=manifest_path,
    )

    assert record.skipped_cached is True
    assert dest.read_bytes() == b"already cached content"
    assert len(calls) == 0  # no network call made


def test_download_file_is_idempotent_across_runs(tmp_path):
    dest = tmp_path / "raw_cache" / "dataset_a" / "file.zip"
    manifest_path = tmp_path / "manifest.json"
    client = _mock_client(b"content")

    r1 = download_file(
        dataset="dataset_a", url="https://www.cms.gov/x/file.zip", dest=dest,
        client=client, manifest_path=manifest_path,
    )
    client2 = _mock_client(b"content")
    r2 = download_file(
        dataset="dataset_a", url="https://www.cms.gov/x/file.zip", dest=dest,
        client=client2, manifest_path=manifest_path,
    )

    assert r1.sha256 == r2.sha256
    assert r2.skipped_cached is True


def test_download_file_raises_on_http_error_status(tmp_path):
    dest = tmp_path / "raw_cache" / "dataset_a" / "missing.zip"
    manifest_path = tmp_path / "manifest.json"
    client = _mock_client(b"not found", status_code=404)

    with pytest.raises(httpx.HTTPStatusError):
        download_file(
            dataset="dataset_a", url="https://www.cms.gov/x/missing.zip", dest=dest,
            client=client, manifest_path=manifest_path,
        )
    assert not dest.exists()


class TestHostAllowlist:
    def test_allowed_host_passes(self):
        from ingest.base import _check_host_allowed

        _check_host_allowed("https://www.cms.gov/files/zip/foo.zip")
        _check_host_allowed("https://www2.census.gov/programs-surveys/acs/x.dat")

    def test_disallowed_host_raises(self, tmp_path):
        import pytest

        from ingest.base import DisallowedHostError, download_file

        with pytest.raises(DisallowedHostError):
            download_file(
                dataset="evil",
                url="https://evil.example.com/payload.zip",
                dest=tmp_path / "payload.zip",
                manifest_path=tmp_path / "manifest.json",
            )

    def test_cached_file_skips_check(self, tmp_path):
        # cache-first: an existing dest is re-recorded without any network
        # call, so the allowlist (a network guard) must not break warm reruns
        # even if the recorded URL's host later left the allowlist.
        from ingest.base import download_file

        dest = tmp_path / "cached.zip"
        dest.write_bytes(b"cached-bytes")
        record = download_file(
            dataset="cached",
            url="https://evil.example.com/cached.zip",
            dest=dest,
            manifest_path=tmp_path / "manifest.json",
        )
        assert record.skipped_cached is True
