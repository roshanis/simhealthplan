"""Tests for ingest/census_acs.py URL construction (keyless flat-file route).

Hermetic — no network. Verifies the primary (keyless) download URLs match
the confirmed www2.census.gov table-based summary file layout, and that the
optional api.census.gov fallback refuses to run without a configured key.
"""

from __future__ import annotations

import pytest

from ingest import census_acs


def test_tables_cover_all_four_required_variables():
    assert census_acs.TABLES == ["b01001", "b03002", "c17002", "b19037"]


def test_table_data_url_matches_confirmed_layout():
    assert census_acs.table_data_url("b01001") == (
        "https://www2.census.gov/programs-surveys/acs/summary_file/2022/"
        "table-based-SF/data/5YRData/acsdt5y2022-b01001.dat"
    )


def test_maricopa_geo_id_format():
    assert census_acs.MARICOPA_GEO_ID == "0500000US04013"


def test_table_shells_url():
    assert census_acs.TABLE_SHELLS_URL == (
        "https://www2.census.gov/programs-surveys/acs/summary_file/2022/"
        "table-based-SF/documentation/ACS20225YR_Table_Shells.txt"
    )


def test_fetch_via_api_requires_key(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "CENSUS_API_KEY", None)
    with pytest.raises(RuntimeError, match="CENSUS_API_KEY"):
        census_acs.fetch_via_api(["NAME", "B01001_001E"])
