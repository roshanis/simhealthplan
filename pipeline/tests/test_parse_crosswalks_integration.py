"""Integration test: parse/crosswalks.py against the real downloaded files.

Requires landscape_2024.parquet to already exist in data/interim (run
parse/landscape.py first) so the plan crosswalk can be filtered to
Maricopa Year-1 plans.
"""

from __future__ import annotations

import pytest

from config.settings import settings
from parse import crosswalks

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def parsed():
    cache_dir = settings.RAW_CACHE_DIR / crosswalks.DATASET
    if not cache_dir.exists() or not any(cache_dir.glob("ssa_fips_state_county_*.csv")):
        pytest.skip(f"{cache_dir} not populated; run `make ingest` first")
    if not (settings.INTERIM_DIR / "landscape_2024.parquet").exists():
        pytest.skip("landscape_2024.parquet missing; run parse/landscape.py first")
    return crosswalks.run()


def test_ssa_fips_contains_maricopa(parsed):
    ssa_fips_df, _plan_df = parsed
    row = ssa_fips_df.set_index("fips").loc[settings.COUNTY_FIPS]
    assert row["county"].upper() == "MARICOPA"
    assert row["ssa"] == "03060"


def test_plan_crosswalk_resolution_rate_at_least_90_percent(parsed):
    import pandas as pd

    _ssa_fips_df, plan_df = parsed
    landscape_2024 = pd.read_parquet(settings.INTERIM_DIR / "landscape_2024.parquet")
    maricopa_keys = set(zip(landscape_2024["contract_id"], landscape_2024["plan_id"]))

    rate = crosswalks.resolution_rate(plan_df, maricopa_keys)
    assert rate >= 0.90, f"plan crosswalk resolution rate {rate:.1%} below 90% threshold"


def test_interim_parquet_files_written(parsed):
    assert (settings.INTERIM_DIR / "ssa_fips_crosswalk.parquet").exists()
    assert (settings.INTERIM_DIR / "plan_crosswalk_2024_2025.parquet").exists()
