"""Tests for parse/cpsc.py — Monthly Enrollment by CPSC.

TDD against a small committed fixture (tests/fixtures/cpsc_enrollment_sample.csv)
mirroring the real CMS column headers and the empirically-observed
suppression sentinel ("*" for enrollment <= 10, verified against the real
March 2024 national file). Hermetic — no network.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from parse import cpsc

FIXTURES = Path(__file__).parent / "fixtures"


def test_suppression_sentinel_is_asterisk():
    assert cpsc.SUPPRESSION_SENTINEL == "*"


def test_parse_enrollment_bytes_filters_to_fips_and_flags_suppression():
    raw = (FIXTURES / "cpsc_enrollment_sample.csv").read_bytes()
    df = cpsc.parse_enrollment_bytes(raw, fips="04013", year_month="2024-03")

    assert list(df.columns) == cpsc.EXPECTED_COLUMNS
    # The Alabama decoy row and the row with a blank FIPS code must be excluded.
    assert (df["fips"] == "04013").all()
    assert len(df) == 5  # E3014/801, E3014/802, H0022/001, H0028/021, H0028/023

    row = df.set_index(["contract_id", "plan_id"]).loc[("E3014", "801")]
    assert row["enrollment"] == 156
    assert row["suppressed"] == False  # noqa: E712

    suppressed_row = df.set_index(["contract_id", "plan_id"]).loc[("E3014", "802")]
    assert pd.isna(suppressed_row["enrollment"])
    assert suppressed_row["suppressed"] == True  # noqa: E712

    assert df["enrollment"].dtype.name == "Int64"
    assert df["year_month"].unique().tolist() == ["2024-03"]


def test_parse_enrollment_bytes_excludes_blank_fips_row():
    raw = (FIXTURES / "cpsc_enrollment_sample.csv").read_bytes()
    df = cpsc.parse_enrollment_bytes(raw, fips="04013", year_month="2024-03")
    keys = set(zip(df["contract_id"], df["plan_id"]))
    assert ("H0028", "099") not in keys  # Alabama decoy
    assert keys == {("E3014", "801"), ("E3014", "802"), ("H0022", "001"), ("H0028", "021")} | {("H0028", "023")}


def test_find_enrollment_entry_matches_expected_filename():
    names = [
        "CPSC_Enrollment_2024_03/",
        "CPSC_Enrollment_2024_03/CPSC_Contract_Info_2024_03.csv",
        "CPSC_Enrollment_2024_03/CPSC_Enrollment_Info_2024_03.csv",
        "CPSC_Enrollment_2024_03/Read_Me_CPSC_Enrollment_2024.txt",
    ]
    assert cpsc.find_enrollment_entry(names) == "CPSC_Enrollment_2024_03/CPSC_Enrollment_Info_2024_03.csv"
