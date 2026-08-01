"""Integration test: parse/cpsc.py against the real downloaded CPSC zips.

Skips cleanly if data/raw_cache/cpsc/... hasn't been downloaded yet.
Run `make ingest` or `uv run python -m ingest.cpsc` first.
"""

from __future__ import annotations

import pytest

from config.settings import settings
from parse import cpsc

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def parsed():
    cache_dir = settings.RAW_CACHE_DIR / cpsc.DATASET
    if not cache_dir.exists() or not any(cache_dir.glob("2024_03__*")):
        pytest.skip(f"{cache_dir} not populated; run `make ingest` first")
    return cpsc.run()


def test_maricopa_total_enrollment_plausible(parsed):
    df_2024, df_2025 = parsed
    total_2024 = df_2024["enrollment"].sum()
    total_2025 = df_2025["enrollment"].sum()
    assert total_2024 > 300_000, f"2024 Maricopa MA enrollment implausibly low: {total_2024}"
    assert total_2025 > 300_000, f"2025 Maricopa MA enrollment implausibly low: {total_2025}"


def test_suppressed_rows_have_null_enrollment(parsed):
    df_2024, _df_2025 = parsed
    suppressed = df_2024[df_2024["suppressed"]]
    assert len(suppressed) > 0
    assert suppressed["enrollment"].isna().all()


def test_interim_parquet_files_written(parsed):
    assert (settings.INTERIM_DIR / "cpsc_2024_03.parquet").exists()
    assert (settings.INTERIM_DIR / "cpsc_2025_03.parquet").exists()
