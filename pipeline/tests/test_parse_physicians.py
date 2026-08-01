"""Tests for parse/physicians.py — DAC roster parsing + Maricopa physician-supply summary.

TDD against small committed fixtures mirroring the real CMS Doctors and
Clinicians National Downloadable File (modern mixed-style headers, e.g.
"Provider Last Name" / "City/Town" alongside legacy codes like "pri_spec")
and the Census 2020 ZCTA->county relationship file.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from parse import physicians

FIXTURES = Path(__file__).parent / "fixtures"


def _zcta_county() -> pd.DataFrame:
    return physicians.parse_zcta_county((FIXTURES / "zcta_county_sample.txt").read_bytes())


def _maricopa_df() -> pd.DataFrame:
    keep = physicians.county_zips(_zcta_county())
    return physicians.parse_dac(FIXTURES / "dac_national_sample.csv", keep)


# --- ZCTA -> county ------------------------------------------------------------


def test_parse_zcta_county_assigns_max_land_area_county():
    df = _zcta_county()
    by_zcta = df.set_index("zcta")["county_fips"]

    assert by_zcta["85004"] == "04013"
    # 85142 straddles Maricopa (3M m^2) and Pinal (9M m^2): Pinal wins.
    assert by_zcta["85142"] == "04021"
    # One row per ZCTA, blank-ZCTA remainder rows dropped.
    assert df["zcta"].is_unique
    assert "" not in set(df["zcta"])


def test_county_zips_returns_maricopa_assigned_zctas_only():
    zips = physicians.county_zips(_zcta_county())
    assert zips == {"85004", "85201", "85304"}


def test_parse_zcta_county_raises_on_missing_required_columns():
    bad = b"GEOID_ZCTA5_20|SOMETHING_ELSE\n85004|1\n"
    with pytest.raises(RuntimeError, match="GEOID_COUNTY_20"):
        physicians.parse_zcta_county(bad)


# --- DAC parsing ---------------------------------------------------------------


def test_parse_dac_filters_to_state_and_county_zips():
    df = _maricopa_df()

    # Tucson (Pima ZIP), Los Angeles (CA), and Safford (Graham ZIP) are out.
    assert set(df["npi"]) == {"1000000001", "1000000002", "1000000003"}
    # Row-level: Dr. Smith practices at two Maricopa addresses -> two rows.
    assert len(df) == 4
    assert list(df.columns) == physicians.INTERIM_COLUMNS


def test_parse_dac_normalizes_mixed_style_headers_and_zip5():
    df = _maricopa_df()
    smith = df[df["npi"] == "1000000001"].iloc[0]

    # "Provider Last Name" / "City/Town" / "ZIP Code" style headers resolve.
    assert smith["last_name"] == "SMITH"
    assert smith["city"] == "PHOENIX"
    # 9-digit ZIPs truncate to 5.
    assert set(df["zip5"]) == {"85004", "85201", "85304"}
    # "Facility Name" resolves to org_name.
    assert set(df["org_name"]) == {"BANNER HEALTH", "VALLEY CARE MEDICAL GROUP"}


def test_resolve_columns_accepts_legacy_lowercase_headers():
    legacy = ["NPI", "lst_nm", "frst_nm", "gndr", "Cred", "Med_sch", "Grd_yr",
              "pri_spec", "sec_spec_all", "Telehlth", "org_nm", "org_pac_id",
              "num_org_mem", "cty", "st", "zip", "adrs_id"]
    resolved = physicians._resolve_columns(legacy)
    assert resolved["last_name"] == "lst_nm"
    assert resolved["org_name"] == "org_nm"
    assert resolved["city"] == "cty"
    assert resolved["state"] == "st"
    assert resolved["zip"] == "zip"


def test_resolve_columns_raises_listing_actual_header_when_required_missing():
    with pytest.raises(RuntimeError, match="pri_spec|primary_specialty"):
        physicians._resolve_columns(["NPI", "st", "zip", "unrelated_column"])


# --- aggregation ---------------------------------------------------------------


def test_build_summary_counts_unique_clinicians_not_rows():
    summary = physicians.build_summary(_maricopa_df())
    totals = summary["totals"]

    assert totals["clinicians"] == 3  # Smith's two addresses count once
    assert totals["organizations"] == 2
    assert totals["practice_locations"] == 4  # unique (npi, address)
    assert totals["specialties"] == 2


def test_build_summary_telehealth_is_any_y_per_clinician():
    summary = physicians.build_summary(_maricopa_df())
    # Smith: Y at one address, blank at the other -> counts as telehealth.
    # Nguyen: N. Ortiz: Y. -> 2/3.
    assert summary["totals"]["telehealth_share"] == pytest.approx(2 / 3)


def test_build_summary_top_specialties_and_orgs():
    summary = physicians.build_summary(_maricopa_df())

    assert summary["top_specialties"][0] == {"specialty": "INTERNAL MEDICINE", "clinicians": 2}
    assert summary["top_specialties"][1] == {
        "specialty": "CARDIOVASCULAR DISEASE (CARDIOLOGY)",
        "clinicians": 1,
    }

    assert summary["top_organizations"][0] == {"org_name": "BANNER HEALTH", "clinicians": 2}
    assert summary["top_organizations"][1] == {"org_name": "VALLEY CARE MEDICAL GROUP", "clinicians": 1}


def test_build_summary_metadata_documents_proxy_and_no_network_linkage():
    summary = physicians.build_summary(_maricopa_df())
    metadata = summary["metadata"]

    assert metadata["county_fips"] == "04013"
    assert metadata["zip_zcta_proxy"] is True
    # The honest-limitations contract: this data never links to plan networks.
    assert metadata["network_linkage"] is False


def test_build_summary_empty_input():
    empty = pd.DataFrame(columns=physicians.INTERIM_COLUMNS)
    summary = physicians.build_summary(empty)
    assert summary["totals"]["clinicians"] == 0
    assert summary["totals"]["telehealth_share"] == 0.0
    assert summary["top_specialties"] == []
    assert summary["top_organizations"] == []
