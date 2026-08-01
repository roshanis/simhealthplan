"""Integration test: parse/landscape.py against the real downloaded archive.

Skips cleanly if data/raw_cache/landscape/... hasn't been downloaded yet
(e.g. CI without network access). Run `make ingest` or
`uv run python -m ingest.landscape` first to populate the cache.
"""

from __future__ import annotations

import pytest

from config.settings import settings
from parse import landscape

ARCHIVE_PATH = settings.RAW_CACHE_DIR / landscape.DATASET / landscape.ARCHIVE_NAME

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def parsed():
    if not ARCHIVE_PATH.exists():
        pytest.skip(f"{ARCHIVE_PATH} not downloaded; run `make ingest` first")
    return landscape.run(ARCHIVE_PATH)


def test_maricopa_plan_counts_in_expected_range(parsed):
    df2024, df2025 = parsed
    assert 20 <= len(df2024) <= 120, f"2024 plan count {len(df2024)} out of range"
    assert 20 <= len(df2025) <= 120, f"2025 plan count {len(df2025)} out of range"


def test_premium_star_plan_type_non_null(parsed):
    for year, df in zip((2024, 2025), parsed):
        assert df["premium_part_c"].notna().all(), f"{year}: null premium_part_c"
        assert df["premium_part_d"].notna().all(), f"{year}: null premium_part_d"
        assert df["star_rating"].notna().all(), f"{year}: null star_rating"
        assert df["plan_type"].notna().all(), f"{year}: null plan_type"


def test_schemas_identical_across_years(parsed):
    df2024, df2025 = parsed
    assert list(df2024.columns) == list(df2025.columns)
    for col in landscape.EXPECTED_COLUMNS:
        assert df2024[col].dtype == df2025[col].dtype, f"dtype mismatch for {col!r}"


def test_interim_parquet_files_written(parsed):
    assert (settings.INTERIM_DIR / "landscape_2024.parquet").exists()
    assert (settings.INTERIM_DIR / "landscape_2025.parquet").exists()
