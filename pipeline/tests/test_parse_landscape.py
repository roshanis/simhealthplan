"""Tests for parse/landscape.py — MA & Part D Landscape, CY2024 + CY2025.

TDD against small committed fixtures (tests/fixtures/landscape_2024_*.csv,
landscape_2025.csv) that mirror the real CMS column headers verified during
development (see module docstring in parse/landscape.py for the schema
break between years). Fully hermetic — no network, no real archive needed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from parse import landscape

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_COLUMNS = [
    "contract_id",
    "plan_id",
    "segment_id",
    "state",
    "county",
    "org_name",
    "plan_name",
    "plan_type",
    "snp_type",
    "premium_part_c",
    "premium_part_d",
    "deductible",
    "moop_inn",
    "star_rating",
    "year",
]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$5,100.00 ", 5100.0),
        ("$0.00 ", 0.0),
        ("", None),
        (None, None),
        ("$37.00 ", 37.0),
        ("225.00", 225.0),
    ],
)
def test_money_to_float(raw, expected):
    assert landscape.money_to_float(raw) == expected


def test_parse_2024_normalizes_schema_and_filters_to_maricopa():
    df = landscape.parse_2024(
        ma_bytes=(FIXTURES / "landscape_2024_ma.csv").read_bytes(),
        snp_bytes=(FIXTURES / "landscape_2024_snp.csv").read_bytes(),
        premium_bytes=(FIXTURES / "landscape_2024_premium.csv").read_bytes(),
    )

    assert list(df.columns) == EXPECTED_COLUMNS
    assert (df["county"] == "Maricopa").all()
    assert (df["state"] == "AZ").all()
    assert (df["year"] == 2024).all()

    # Union of non-SNP (MA file) + SNP file Maricopa rows, deduped by key.
    keys = set(zip(df["contract_id"], df["plan_id"], df["segment_id"]))
    assert keys == {
        ("H0028", "023", "0"),
        ("H0028", "027", "0"),
        ("H0302", "001", "0"),
        ("H3551", "003", "0"),
        ("H0321", "002", "0"),
        ("H0351", "038", "0"),
    }

    # premium/star/plan_type must be non-null for every row (acceptance criterion).
    assert df["premium_part_c"].notna().all()
    assert df["premium_part_d"].notna().all()
    assert df["star_rating"].notna().all()
    assert df["plan_type"].notna().all()

    # H0028-023 comes from the Plan Premium Report split.
    row = df.set_index(["contract_id", "plan_id"]).loc[("H0028", "023")]
    assert row["premium_part_c"] == 1.90
    assert row["premium_part_d"] == 35.10

    # H3551-003 has no Plan Premium Report row (verified against real CMS
    # data: "premium giveback" / no-Part-D plans are absent from that file).
    # Fallback: split the MA file's consolidated premium as (consolidated, 0).
    fallback = df.set_index(["contract_id", "plan_id"]).loc[("H3551", "003")]
    assert fallback["premium_part_c"] == 0.0
    assert fallback["premium_part_d"] == 0.0
    assert fallback["star_rating"] == "Plan too new to be measured"

    # snp_type: populated from the SNP file for SNP plans, a normalized
    # non-null sentinel for everyone else.
    snp_row = df.set_index(["contract_id", "plan_id"]).loc[("H0321", "002")]
    assert snp_row["snp_type"] == "Dual-Eligible"
    non_snp_row = df.set_index(["contract_id", "plan_id"]).loc[("H0028", "023")]
    assert non_snp_row["snp_type"] in ("Not Applicable", "None")


def test_parse_2025_normalizes_schema_and_filters_to_maricopa():
    df = landscape.parse_2025(csv_bytes=(FIXTURES / "landscape_2025.csv").read_bytes())

    assert list(df.columns) == EXPECTED_COLUMNS
    assert (df["county"] == "Maricopa").all()
    assert (df["state"] == "AZ").all()
    assert (df["year"] == 2025).all()

    keys = set(zip(df["contract_id"], df["plan_id"], df["segment_id"]))
    # Pima decoy and the national PDP ("(All Counties)") row must be excluded.
    assert ("H0432", "009", "0") not in keys
    assert ("S1030", "001", "0") not in keys
    assert keys == {
        ("H0028", "023", "0"),
        ("H0028", "027", "0"),
        ("H0321", "002", "0"),
        ("H3551", "003", "0"),
        ("R7220", "001", "0"),
    }

    assert df["premium_part_c"].notna().all()
    assert df["premium_part_d"].notna().all()
    assert df["star_rating"].notna().all()
    assert df["plan_type"].notna().all()

    row = df.set_index(["contract_id", "plan_id"]).loc[("H0028", "023")]
    assert row["premium_part_c"] == 17.00
    assert row["premium_part_d"] == 0.0
    assert row["snp_type"] == "Not Applicable"

    snp_row = df.set_index(["contract_id", "plan_id"]).loc[("H0321", "002")]
    assert snp_row["snp_type"] == "Dual-Eligible"

    no_rating_row = df.set_index(["contract_id", "plan_id"]).loc[("H3551", "003")]
    assert no_rating_row["star_rating"] == "Not Enough Data Available"

    # R7220-001 is an MA-only plan with no Part D benefit at all ("Part D
    # Total Premium" == "Not Applicable" in the raw CMS file, not a number).
    # We treat "not applicable" as $0 so premium_part_d stays non-null.
    no_partd_row = df.set_index(["contract_id", "plan_id"]).loc[("R7220", "001")]
    assert no_partd_row["premium_part_d"] == 0.0
    assert no_partd_row["premium_part_c"] == 0.0


def test_2024_and_2025_schemas_are_identical():
    df2024 = landscape.parse_2024(
        ma_bytes=(FIXTURES / "landscape_2024_ma.csv").read_bytes(),
        snp_bytes=(FIXTURES / "landscape_2024_snp.csv").read_bytes(),
        premium_bytes=(FIXTURES / "landscape_2024_premium.csv").read_bytes(),
    )
    df2025 = landscape.parse_2025(csv_bytes=(FIXTURES / "landscape_2025.csv").read_bytes())

    assert list(df2024.columns) == list(df2025.columns)
    for col in EXPECTED_COLUMNS:
        assert df2024[col].dtype == df2025[col].dtype, f"dtype mismatch for {col!r}"
