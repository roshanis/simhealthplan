"""Tests for parse/crosswalks.py — SSA<->FIPS crosswalk + CMS plan crosswalk.

TDD against small committed fixtures mirroring the real NBER and CMS files.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from parse import crosswalks

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_ssa_fips_normalizes_columns():
    raw = (FIXTURES / "ssa_fips_crosswalk_sample.csv").read_bytes()
    df = crosswalks.parse_ssa_fips(raw)

    assert list(df.columns) == ["fips", "county", "state", "ssa"]
    row = df.set_index("fips").loc["04013"]
    assert row["county"] == "MARICOPA"
    assert row["state"] == "AZ"
    assert row["ssa"] == "03060"
    assert len(df) == 4  # all counties kept, not just Maricopa


def test_parse_plan_crosswalk_normalizes_schema_and_maps_disposition():
    raw = (FIXTURES / "plan_crosswalk_sample.txt").read_bytes()
    df = crosswalks.parse_plan_crosswalk(raw)

    assert list(df.columns) == crosswalks.PLAN_CROSSWALK_COLUMNS

    renewed = df[(df["old_contract_id"] == "H0028") & (df["old_plan_id"] == "023")].iloc[0]
    assert renewed["disposition"] == "renewed"
    assert renewed["new_contract_id"] == "H0028"
    assert renewed["new_plan_id"] == "023"
    assert renewed["old_segment_id"] == "0"
    assert renewed["new_segment_id"] == "0"

    renumbered = df[(df["old_contract_id"] == "H0028") & (df["old_plan_id"] == "052")].iloc[0]
    assert renumbered["disposition"] == "renumbered"
    assert renumbered["new_plan_id"] == "074"

    consolidated = df[(df["old_contract_id"] == "H0294") & (df["old_plan_id"] == "017")].iloc[0]
    assert consolidated["disposition"] == "consolidated"

    terminated = df[(df["old_contract_id"] == "H0028") & (df["old_plan_id"] == "050")].iloc[0]
    assert terminated["disposition"] == "terminated"
    assert pd.isna(terminated["new_contract_id"]) or terminated["new_contract_id"] in ("TERMINATED", None)

    new_plan = df[(df["new_contract_id"] == "H0028") & (df["new_plan_id"] == "065")].iloc[0]
    assert new_plan["disposition"] == "new"


def test_filter_to_plans_keeps_only_given_keys():
    raw = (FIXTURES / "plan_crosswalk_sample.txt").read_bytes()
    df = crosswalks.parse_plan_crosswalk(raw)
    maricopa_keys = {("H0028", "023"), ("H0028", "052"), ("H0294", "017"), ("H0028", "050")}

    filtered = crosswalks.filter_to_plans(df, maricopa_keys)

    assert set(zip(filtered["old_contract_id"], filtered["old_plan_id"])) <= maricopa_keys
    assert "H9999" not in filtered["old_contract_id"].tolist()


def test_resolution_rate():
    raw = (FIXTURES / "plan_crosswalk_sample.txt").read_bytes()
    df = crosswalks.parse_plan_crosswalk(raw)
    maricopa_keys = {("H0028", "023"), ("H0028", "052"), ("H0294", "017"), ("H0028", "050")}

    rate = crosswalks.resolution_rate(df, maricopa_keys)
    assert rate == 1.0
