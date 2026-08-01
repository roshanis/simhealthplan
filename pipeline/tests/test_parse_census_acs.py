"""Tests for parse/census_acs.py — ACS 5-year table-based summary files.

TDD against small committed fixtures mirroring the real pipe-delimited
national .dat files (verified format: GEO_ID then alternating
<TABLE>_E<NNN>/<TABLE>_M<NNN> estimate/margin-of-error column pairs) and
the table shells documentation file used for variable labels.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parse import census_acs

FIXTURES = Path(__file__).parent / "fixtures"


def test_is_census_null_sentinel():
    assert census_acs.is_census_null_sentinel(-555555555)
    assert census_acs.is_census_null_sentinel(-222222222)
    assert not census_acs.is_census_null_sentinel(102)
    assert not census_acs.is_census_null_sentinel(4430871)


def test_find_geo_row_returns_maricopa_only():
    path = FIXTURES / "acs_b01001_sample.dat"
    header, values = census_acs.find_geo_row(path, geo_id="0500000US04013")
    assert header[0] == "GEO_ID"
    assert values[0] == "0500000US04013"
    assert values[header.index("B01001_E001")] == "4430871"


def test_find_geo_row_raises_if_not_found():
    path = FIXTURES / "acs_b01001_sample.dat"
    with pytest.raises(RuntimeError, match="0599999US99999"):
        census_acs.find_geo_row(path, geo_id="0599999US99999")


def test_load_table_shells():
    raw = (FIXTURES / "acs_table_shells_sample.txt").read_bytes()
    shells = census_acs.load_table_shells(raw)
    row = shells.set_index("Unique ID").loc["B01001_002"]
    assert row["Label"] == "Male:"
    assert row["Title"] == "Sex by Age"


def test_tidy_table_produces_one_row_per_variable_with_label():
    dat_path = FIXTURES / "acs_b01001_sample.dat"
    shells = census_acs.load_table_shells((FIXTURES / "acs_table_shells_sample.txt").read_bytes())
    header, values = census_acs.find_geo_row(dat_path, geo_id="0500000US04013")

    df = census_acs.tidy_table("b01001", header, values, shells)

    assert list(df.columns) == census_acs.EXPECTED_COLUMNS
    assert len(df) == 3  # 3 variables in the fixture

    total = df.set_index("variable_code").loc["B01001_001"]
    assert total["estimate"] == 4430871
    assert total["margin_of_error"] is None or (total["margin_of_error"] != total["margin_of_error"])  # NaN
    assert total["label"] == "Total:"
    assert total["table_id"] == "B01001"

    male = df.set_index("variable_code").loc["B01001_002"]
    assert male["estimate"] == 2208150
    assert male["margin_of_error"] == 102
    assert male["label"] == "Male:"
