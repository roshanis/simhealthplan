"""Tests for archetypes/acs_marginals.py — ACS 65+ demographic marginals.

TDD against small synthetic ACS-shaped DataFrames mirroring the real tidy
schema (table_id, variable_code, label, estimate). The integration test
exercises the real data/interim/acs_maricopa.parquet.
"""

from __future__ import annotations

import pandas as pd
import pytest

from archetypes import acs_marginals
from archetypes.constants import AGE_BANDS, INCOME_TIERS, RACE_ETH_GROUPS
from config.settings import settings


def _row(table_id, variable_code, label, estimate):
    return {"table_id": table_id, "variable_code": variable_code, "label": label, "estimate": estimate}


@pytest.fixture
def synthetic_acs():
    rows = []
    # B01001 age/sex: only the 65+ bins matter for age_band_shares.
    # 65-69 = (10+10)+(10+10) = 40; 70-74 = 20+20 = 40; 75-84 = (15+5)+(15+5)
    # = 40; 85+ = 10+10 = 20. Total 65+ = 140.
    b01001 = {
        "B01001_020": ("65 and 66 years", 10),
        "B01001_021": ("67 to 69 years", 10),
        "B01001_022": ("70 to 74 years", 20),
        "B01001_023": ("75 to 79 years", 15),
        "B01001_024": ("80 to 84 years", 5),
        "B01001_025": ("85 years and over", 10),
        "B01001_044": ("65 and 66 years", 10),
        "B01001_045": ("67 to 69 years", 10),
        "B01001_046": ("70 to 74 years", 20),
        "B01001_047": ("75 to 79 years", 15),
        "B01001_048": ("80 to 84 years", 5),
        "B01001_049": ("85 years and over", 10),
    }
    for code, (label, est) in b01001.items():
        rows.append(_row("B01001", code, label, est))

    # B03002 race/ethnicity (total population, used as a proxy shape).
    # white 60 + black 10 + asian 10 + hispanic 15 + other/multi 5 = 100.
    b03002 = {
        "B03002_003": ("White alone", 60),
        "B03002_004": ("Black or African American alone", 10),
        "B03002_006": ("Asian alone", 10),
        "B03002_005": ("American Indian and Alaska Native alone", 2),
        "B03002_007": ("Native Hawaiian and Other Pacific Islander alone", 1),
        "B03002_008": ("Some other race alone", 1),
        "B03002_009": ("Two or more races:", 1),
        "B03002_012": ("Hispanic or Latino:", 15),
    }
    for code, (label, est) in b03002.items():
        rows.append(_row("B03002", code, label, est))

    # C17002 income-to-poverty ratio (all ages) -> <150% FPL target share.
    # (50+50+0+0)/600 = 16.67%, exactly matching the <$25k cumulative share
    # of the B19037 65+ distribution below (100/600), so the cutoff pick is
    # unambiguous.
    c17002 = {
        "C17002_001": ("Total:", 600),
        "C17002_002": ("Under .50", 50),
        "C17002_003": (".50 to .99", 50),
        "C17002_004": ("1.00 to 1.24", 0),
        "C17002_005": ("1.25 to 1.49", 0),
        "C17002_006": ("1.50 to 1.84", 100),
        "C17002_007": ("1.85 to 1.99", 100),
        "C17002_008": ("2.00 and over", 300),
    }
    for code, (label, est) in c17002.items():
        rows.append(_row("C17002", code, label, est))

    # B19037 65+ householder income bins; sums to 600 total.
    b19037 = {
        "B19037_054": ("Less than $10,000", 25),
        "B19037_055": ("$10,000 to $14,999", 25),
        "B19037_056": ("$15,000 to $19,999", 25),
        "B19037_057": ("$20,000 to $24,999", 25),
        "B19037_058": ("$25,000 to $29,999", 50),
        "B19037_059": ("$30,000 to $34,999", 50),
        "B19037_060": ("$35,000 to $39,999", 50),
        "B19037_061": ("$40,000 to $44,999", 50),
        "B19037_062": ("$45,000 to $49,999", 50),
        "B19037_063": ("$50,000 to $59,999", 50),
        "B19037_064": ("$60,000 to $74,999", 50),
        "B19037_065": ("$75,000 to $99,999", 30),
        "B19037_066": ("$100,000 to $124,999", 30),
        "B19037_067": ("$125,000 to $149,999", 20),
        "B19037_068": ("$150,000 to $199,999", 20),
        "B19037_069": ("$200,000 or more", 50),
    }
    for code, (label, est) in b19037.items():
        rows.append(_row("B19037", code, label, est))

    return pd.DataFrame(rows)


def test_age_band_shares_sum_to_one_and_use_correct_bins(synthetic_acs):
    shares = acs_marginals.age_band_shares(synthetic_acs)
    assert set(shares.keys()) == set(AGE_BANDS)
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-9)
    assert shares["65-69"] == pytest.approx(40 / 140)
    assert shares["70-74"] == pytest.approx(40 / 140)
    assert shares["75-84"] == pytest.approx(40 / 140)
    assert shares["85+"] == pytest.approx(20 / 140)


def test_race_eth_shares_sum_to_one_and_match_categories(synthetic_acs):
    shares = acs_marginals.race_eth_shares(synthetic_acs)
    assert set(shares.keys()) == set(RACE_ETH_GROUPS)
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-9)
    assert shares["white_nh"] == pytest.approx(60 / 100)
    assert shares["hispanic"] == pytest.approx(15 / 100)
    assert shares["black_nh"] == pytest.approx(10 / 100)
    assert shares["asian_nh"] == pytest.approx(10 / 100)
    assert shares["other_multi_nh"] == pytest.approx(5 / 100)


def test_income_tier_shares_sum_to_one_and_anchor_to_fpl_target(synthetic_acs):
    shares, meta = acs_marginals.income_tier_shares(synthetic_acs)
    assert set(shares.keys()) == set(INCOME_TIERS)
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-9)
    assert shares["low_dual_proxy"] == pytest.approx(100 / 600)
    assert meta["target_share_lt_150_fpl"] == pytest.approx(100 / 600)
    assert meta["low_dual_proxy_cutoff_dollars"] == 25000
    assert shares["middle"] > 0
    assert shares["higher"] > 0


def test_income_tier_shares_middle_split_near_median_of_remainder(synthetic_acs):
    shares, meta = acs_marginals.income_tier_shares(synthetic_acs)
    # remaining = 500 of 600; cumulative from $25k bin: 50,100,150,200,250 --
    # exactly half of 500 at the $45k-$50k bin boundary, so middle covers
    # [$25k, $50k) and higher covers [$50k, +).
    assert meta["middle_cutoff_dollars"] == 50000
    assert shares["middle"] == pytest.approx(250 / 600)
    assert shares["higher"] == pytest.approx(250 / 600)


def test_build_marginals_bundles_all_three(synthetic_acs):
    marginals = acs_marginals.build_marginals(synthetic_acs)
    assert marginals.age_band_shares
    assert marginals.race_eth_shares
    assert marginals.income_tier_shares
    assert isinstance(marginals.income_tier_metadata, dict)


@pytest.mark.integration
def test_real_acs_maricopa_marginals():
    path = settings.INTERIM_DIR / "acs_maricopa.parquet"
    if not path.exists():
        pytest.skip(f"{path} not present; run `make ingest` first")
    df = pd.read_parquet(path)
    marginals = acs_marginals.build_marginals(df)

    assert set(marginals.age_band_shares) == set(AGE_BANDS)
    assert sum(marginals.age_band_shares.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(v > 0 for v in marginals.age_band_shares.values())

    assert set(marginals.race_eth_shares) == set(RACE_ETH_GROUPS)
    assert sum(marginals.race_eth_shares.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(v > 0 for v in marginals.race_eth_shares.values())

    assert set(marginals.income_tier_shares) == set(INCOME_TIERS)
    assert sum(marginals.income_tier_shares.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(v > 0 for v in marginals.income_tier_shares.values())
