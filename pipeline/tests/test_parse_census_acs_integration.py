"""Integration test: parse/census_acs.py against the real downloaded .dat files."""

from __future__ import annotations

import pytest

from config.settings import settings
from ingest.census_acs import TABLES
from parse import census_acs

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def parsed():
    cache_dir = settings.RAW_CACHE_DIR / census_acs.DATASET
    if not cache_dir.exists() or not any(cache_dir.glob("acsdt5y2022-*.dat")):
        pytest.skip(f"{cache_dir} not populated; run `make ingest` first")
    return census_acs.run()


def test_all_four_tables_present(parsed):
    assert set(parsed["table_id"].str.lower()) == set(TABLES)


def test_estimates_mostly_populated(parsed):
    # A handful of derived/edge-case variables can legitimately be null
    # sentinels even for a large county; most should resolve.
    assert parsed["estimate"].notna().mean() > 0.9


def test_labels_resolved_from_table_shells(parsed):
    assert parsed["label"].notna().mean() > 0.9


def test_total_population_plausible(parsed):
    total_pop = parsed[parsed["variable_code"] == "B01001_001"]["estimate"].iloc[0]
    # Maricopa County, AZ had ~4.4M residents in the 2018-2022 ACS window.
    assert 3_500_000 < total_pop < 5_500_000


def test_interim_parquet_written(parsed):
    assert (settings.INTERIM_DIR / "acs_maricopa.parquet").exists()
