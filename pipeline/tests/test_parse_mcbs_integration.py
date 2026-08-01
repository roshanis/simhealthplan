"""Integration test: parse/mcbs.py against the real downloaded PUF + codebook."""

from __future__ import annotations

import pytest

from config.settings import settings
from parse import mcbs

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def parsed():
    cache_dir = settings.RAW_CACHE_DIR / mcbs.DATASET
    if not cache_dir.exists() or not (cache_dir / "SFPUF2023_Data.zip").exists():
        pytest.skip(f"{cache_dir} not populated; run `make ingest` first")
    return mcbs.run()


def test_inventory_has_candidates_in_every_category(parsed):
    inventory, _subset = parsed
    for category in mcbs.CATEGORY_KEYWORDS:
        assert len(inventory[category]) > 0, f"no candidate variables found for {category!r}"


def test_subset_has_30_to_60_plus_id_and_weight_columns(parsed):
    _inventory, subset = parsed
    non_admin_cols = [
        c for c in subset.columns if c not in mcbs.ALWAYS_KEEP_COLUMNS + [mcbs.PRIMARY_WEIGHT_COLUMN]
    ]
    assert 20 <= len(non_admin_cols) <= 60
    assert mcbs.PRIMARY_WEIGHT_COLUMN in subset.columns


def test_subset_has_respondent_rows(parsed):
    _inventory, subset = parsed
    assert len(subset) > 1000


def test_interim_files_written(parsed):
    assert (settings.INTERIM_DIR / "mcbs_variable_inventory.json").exists()
    assert (settings.INTERIM_DIR / "mcbs_subset.parquet").exists()
