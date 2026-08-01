"""Tests for parse/penetration.py — MA State/County Penetration, March 2024 + March 2025.

TDD against small committed fixtures that mirror the real CMS files: note
CY2024 zero-pads FIPSST/FIPSCNTY ("04", "013") while CY2025 does not ("4",
"13") — both years are reconciled to a canonical 5-digit FIPS by
zero-padding FIPSST/FIPSCNTY ourselves rather than trusting the "FIPS"
column's own (inconsistently-padded) formatting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parse import penetration

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "raw,expected",
    [("771,696", 771696), ("7,162", 7162), ("", None), (None, None), ("399246", 399246)],
)
def test_money_int(raw, expected):
    assert penetration.money_int(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("51.74%", pytest.approx(0.5174)), ("", None), (None, None), ("60.39%", pytest.approx(0.6039))],
)
def test_pct_to_float(raw, expected):
    assert penetration.pct_to_float(raw) == expected


def test_parse_2024_extracts_maricopa_row_with_zero_padded_fips():
    raw = (FIXTURES / "penetration_2024_03.csv").read_bytes()
    df = penetration.extract_county(raw, fips="04013", year_month="2024-03")

    assert len(df) == 1
    row = df.iloc[0]
    assert row["fips"] == "04013"
    assert row["ssa"] == "03060"
    assert row["eligibles"] == 771696
    assert row["enrolled"] == 399246
    assert row["penetration"] == pytest.approx(0.5174)
    assert row["year_month"] == "2024-03"


def test_parse_2025_extracts_maricopa_row_despite_unpadded_source_fips():
    raw = (FIXTURES / "penetration_2025_03.csv").read_bytes()
    df = penetration.extract_county(raw, fips="04013", year_month="2025-03")

    assert len(df) == 1
    row = df.iloc[0]
    # Real CY2025 file stores FIPS="4013" (unpadded); we reconstruct "04013"
    # from FIPSST/FIPSCNTY so both years key identically.
    assert row["fips"] == "04013"
    assert row["ssa"] == "03060"
    assert row["eligibles"] == 790307
    assert row["enrolled"] == 410634
    assert row["penetration"] == pytest.approx(0.5196)


def test_pending_designation_row_excluded():
    raw = (FIXTURES / "penetration_2024_03.csv").read_bytes()
    df = penetration.extract_county(raw, fips="00000", year_month="2024-03")
    # "Pending State/County Designation" has FIPSST/FIPSCNTY of "00"/"000"
    # -> reconstructed fips "00000"; make sure filtering by real Maricopa
    # FIPS never accidentally matches it.
    df_maricopa = penetration.extract_county(raw, fips="04013", year_month="2024-03")
    assert "Pending" not in "".join(df_maricopa["county"].tolist())
