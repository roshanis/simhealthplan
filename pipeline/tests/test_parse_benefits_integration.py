"""Integration test: parse/benefits.py against the real downloaded PBP zips.

Requires landscape_2024.parquet / landscape_2025.parquet in data/interim
(run parse/landscape.py first).
"""

from __future__ import annotations

import pytest

from config.settings import settings
from parse import benefits

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def parsed():
    cache_dir = settings.RAW_CACHE_DIR / benefits.DATASET
    if not cache_dir.exists() or not any(cache_dir.glob("2024_q1__*.zip")):
        pytest.skip(f"{cache_dir} not populated; run `make ingest` first")
    if not (settings.INTERIM_DIR / "landscape_2024.parquet").exists():
        pytest.skip("landscape parquet files missing; run parse/landscape.py first")
    return benefits.run()


def test_benefit_flags_at_least_95_percent_populated(parsed):
    for year, df in zip((2024, 2025), parsed):
        rate = benefits.coverage_rate(df)
        exceptions = benefits.uncovered_plans(df)
        assert rate >= 0.95, (
            f"{year}: only {rate:.1%} of Maricopa plans have all 4 benefit "
            f"flags populated (auto + manual fallback combined); "
            f"exceptions (contract_id, plan_id, segment_id): {exceptions}"
        )


def test_moop_inn_matches_landscape_coverage(parsed):
    # moop_inn is sourced from parse/landscape.py (PBP publishes no MOOP
    # field at all - see module docstring), so its coverage here should
    # exactly mirror landscape's own moop_inn coverage, including
    # landscape's known CY2024 gap (the SNP source file has no MOOP column
    # -> ~31% of 2024 Maricopa plans, all SNP-sourced, are null there).
    import pandas as pd

    for year, df in zip((2024, 2025), parsed):
        landscape = pd.read_parquet(settings.INTERIM_DIR / f"landscape_{year}.parquet")
        assert df["moop_inn"].notna().sum() == landscape["moop_inn"].notna().sum(), (
            f"{year}: benefits.moop_inn coverage diverged from landscape.moop_inn"
        )


def test_interim_parquet_files_written(parsed):
    assert (settings.INTERIM_DIR / "benefits_2024.parquet").exists()
    assert (settings.INTERIM_DIR / "benefits_2025.parquet").exists()
