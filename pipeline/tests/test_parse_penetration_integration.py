"""Integration test: parse/penetration.py against the real downloaded zips."""

from __future__ import annotations

import pytest

from config.settings import settings
from parse import penetration

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def parsed():
    cache_dir = settings.RAW_CACHE_DIR / penetration.DATASET
    if not cache_dir.exists() or not any(cache_dir.glob("2024_03__*")):
        pytest.skip(f"{cache_dir} not populated; run `make ingest` first")
    return penetration.run()


def test_maricopa_row_found_both_years(parsed):
    df_2024, df_2025 = parsed
    assert len(df_2024) == 1
    assert len(df_2025) == 1
    assert df_2024.iloc[0]["county"] == "Maricopa"
    assert df_2025.iloc[0]["county"] == "Maricopa"


def test_enrolled_plausible(parsed):
    df_2024, df_2025 = parsed
    assert df_2024.iloc[0]["enrolled"] > 300_000
    assert df_2025.iloc[0]["enrolled"] > 300_000


def test_interim_parquet_files_written(parsed):
    assert (settings.INTERIM_DIR / "penetration_2024_03.parquet").exists()
    assert (settings.INTERIM_DIR / "penetration_2025_03.parquet").exists()
