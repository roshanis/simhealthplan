"""Tests for choice_model/plan_attributes.py — canonical per-plan attribute tables.

TDD against small synthetic landscape/benefits/cpsc/crosswalk-shaped
DataFrames. Integration tests exercise the real 2024/2025 interim files and
are marked ``pytest.mark.integration``.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from choice_model import plan_attributes
from choice_model.schemas import PlansFile2024, PlansFile2025
from config.settings import settings


# --- normalize_plan_type -----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Local HMO", "HMO"),
        ("Local PPO", "PPO"),
        ("Regional PPO", "Regional PPO"),
    ],
)
def test_normalize_plan_type_2024_values(raw, expected):
    assert plan_attributes.normalize_plan_type(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("HMO", "HMO"),
        ("PPO", "PPO"),
        ("HMO-POS", "HMO"),
        ("HMO C-SNP", "HMO"),
        ("HMO D-SNP", "HMO"),
        ("HMO-POS C-SNP", "HMO"),
        ("HMO I-SNP", "HMO"),
        ("HMO-POS D-SNP", "HMO"),
        ("Regional PPO", "Regional PPO"),
        ("PPO I-SNP", "PPO"),
        ("HMO-POS I-SNP", "HMO"),
    ],
)
def test_normalize_plan_type_2025_values(raw, expected):
    assert plan_attributes.normalize_plan_type(raw) == expected


def test_normalize_plan_type_unrecognized_raises():
    with pytest.raises(ValueError):
        plan_attributes.normalize_plan_type("PFFS")


# --- parse_star_rating --------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2.5", 2.5),
        ("3.0", 3.0),
        ("3", 3.0),
        ("4.5", 4.5),
        ("5", 5.0),
    ],
)
def test_parse_star_rating_numeric(raw, expected):
    assert plan_attributes.parse_star_rating(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "Not enough data available",
        "Plan too new to be measured",
        "Not Enough Data Available",
        "Plan Too New To Be Measured",
        None,
    ],
)
def test_parse_star_rating_placeholder_returns_none(raw):
    assert plan_attributes.parse_star_rating(raw) is None


# --- impute_star_ratings -------------------------------------------------------


@pytest.fixture
def star_df():
    return pd.DataFrame(
        [
            {"plan_key": "A-1", "plan_type_norm": "HMO", "star_rating": "3.0"},
            {"plan_key": "A-2", "plan_type_norm": "HMO", "star_rating": "5.0"},
            {"plan_key": "A-3", "plan_type_norm": "HMO", "star_rating": "Not enough data available"},
            {"plan_key": "A-4", "plan_type_norm": "PPO", "star_rating": "4.0"},
        ]
    )


def test_impute_star_ratings_uses_type_median_and_flags(star_df):
    out = plan_attributes.impute_star_ratings(star_df)
    row = out.set_index("plan_key").loc["A-3"]
    assert bool(row["imputed_star"]) is True
    # median of HMO known values {3.0, 5.0} == 4.0
    assert row["star_rating_value"] == pytest.approx(4.0)

    known_row = out.set_index("plan_key").loc["A-1"]
    assert bool(known_row["imputed_star"]) is False
    assert known_row["star_rating_value"] == pytest.approx(3.0)


def test_impute_star_ratings_no_nulls_leaves_flags_false():
    df = pd.DataFrame(
        [
            {"plan_key": "A-1", "plan_type_norm": "HMO", "star_rating": "3.0"},
            {"plan_key": "A-2", "plan_type_norm": "HMO", "star_rating": "4.0"},
        ]
    )
    out = plan_attributes.impute_star_ratings(df)
    assert not out["imputed_star"].any()


# --- impute_moop --------------------------------------------------------------


@pytest.fixture
def moop_df():
    return pd.DataFrame(
        [
            {"contract_id": "H0001", "plan_id": "001", "plan_type_norm": "HMO", "moop_inn": 5000.0},
            {"contract_id": "H0001", "plan_id": "002", "plan_type_norm": "HMO", "moop_inn": 7000.0},
            # renewed in crosswalk, 2025 has a value -> crosswalk backfill
            {"contract_id": "H0002", "plan_id": "001", "plan_type_norm": "HMO", "moop_inn": None},
            # not renewed (terminated) -> type-median fallback
            {"contract_id": "H0003", "plan_id": "001", "plan_type_norm": "HMO", "moop_inn": None},
        ]
    )


@pytest.fixture
def crosswalk_df():
    return pd.DataFrame(
        [
            {
                "old_contract_id": "H0002",
                "old_plan_id": "001",
                "new_contract_id": "H0002",
                "new_plan_id": "001",
                "disposition": "renewed",
            },
            {
                "old_contract_id": "H0003",
                "old_plan_id": "001",
                "new_contract_id": "H0003",
                "new_plan_id": "001",
                "disposition": "terminated",
            },
        ]
    )


@pytest.fixture
def other_year_landscape_df():
    return pd.DataFrame(
        [
            {"contract_id": "H0002", "plan_id": "001", "moop_inn": 9350.0},
            {"contract_id": "H0003", "plan_id": "001", "moop_inn": 8800.0},
        ]
    )


def test_impute_moop_crosswalk_backfill_used_when_renewed(moop_df, crosswalk_df, other_year_landscape_df):
    out = plan_attributes.impute_moop(moop_df, crosswalk_df, other_year_landscape_df)
    row = out.set_index(["contract_id", "plan_id"]).loc[("H0002", "001")]
    assert bool(row["imputed_moop"]) is True
    assert row["moop_imputation_method"] == "crosswalk_backfill"
    assert row["moop_imputed_value"] == pytest.approx(9350.0)


def test_impute_moop_falls_back_to_type_median_when_not_renewed(moop_df, crosswalk_df, other_year_landscape_df):
    out = plan_attributes.impute_moop(moop_df, crosswalk_df, other_year_landscape_df)
    row = out.set_index(["contract_id", "plan_id"]).loc[("H0003", "001")]
    assert bool(row["imputed_moop"]) is True
    assert row["moop_imputation_method"] == "type_median"
    # median of known HMO moop {5000, 7000} == 6000 (the crosswalk-backfilled
    # H0002 row is not "known", only the two originally-non-null rows are)
    assert row["moop_imputed_value"] == pytest.approx(6000.0)


def test_impute_moop_no_crosswalk_falls_back_to_type_median(moop_df):
    out = plan_attributes.impute_moop(moop_df, crosswalk_df=None, other_year_landscape_df=None)
    for _, row in out[out["moop_inn"].isna()].iterrows():
        assert bool(row["imputed_moop"]) is True
        assert row["moop_imputation_method"] == "type_median"


def test_impute_moop_no_nulls_leaves_flags_false():
    df = pd.DataFrame(
        [
            {"contract_id": "H0001", "plan_id": "001", "plan_type_norm": "HMO", "moop_inn": 5000.0},
        ]
    )
    out = plan_attributes.impute_moop(df, crosswalk_df=None, other_year_landscape_df=None)
    assert not out["imputed_moop"].any()
    assert out.iloc[0]["moop_imputation_method"] is None


# --- build_plan_table ----------------------------------------------------------


@pytest.fixture
def landscape_df():
    return pd.DataFrame(
        [
            {
                "contract_id": "H0001",
                "plan_id": "001",
                "org_name": "Acme",
                "plan_name": "Acme Gold (HMO)",
                "plan_type": "Local HMO",
                "snp_type": "Not Applicable",
                "premium_part_c": 0.0,
                "premium_part_d": 35.0,
                "deductible": 0.0,
                "moop_inn": 5000.0,
                "star_rating": "4.0",
            },
            {
                "contract_id": "H0002",
                "plan_id": "001",
                "org_name": "Beta",
                "plan_name": "Beta Choice (PPO)",
                "plan_type": "Local PPO",
                "snp_type": "Not Applicable",
                "premium_part_c": 10.0,
                "premium_part_d": 0.0,
                "deductible": 100.0,
                "moop_inn": 6000.0,
                "star_rating": "3.5",
            },
        ]
    )


@pytest.fixture
def benefits_df():
    return pd.DataFrame(
        [
            {
                "contract_id": "H0001",
                "plan_id": "001",
                "has_comprehensive_dental": True,
                "has_vision": True,
                "has_hearing_aids": False,
                "has_otc_or_flex": True,
            },
            {
                "contract_id": "H0002",
                "plan_id": "001",
                "has_comprehensive_dental": False,
                "has_vision": False,
                "has_hearing_aids": False,
                "has_otc_or_flex": False,
            },
        ]
    )


@pytest.fixture
def cpsc_df():
    return pd.DataFrame(
        [
            {"contract_id": "H0001", "plan_id": "001", "enrollment": 400, "suppressed": False},
            {"contract_id": "H0002", "plan_id": "001", "enrollment": pd.NA, "suppressed": True},
        ]
    )


def test_build_plan_table_premium_total_is_sum(landscape_df, benefits_df, cpsc_df):
    table = plan_attributes.build_plan_table(2024, landscape_df, benefits_df, cpsc_df)
    row = table.set_index("plan_key").loc["H0001-001"]
    assert row["premium_total"] == pytest.approx(35.0)


def test_build_plan_table_is_ppo_flag(landscape_df, benefits_df, cpsc_df):
    table = plan_attributes.build_plan_table(2024, landscape_df, benefits_df, cpsc_df)
    idx = table.set_index("plan_key")
    assert idx.loc["H0001-001", "is_ppo"] == False  # noqa: E712
    assert idx.loc["H0002-001", "is_ppo"] == True  # noqa: E712


def test_build_plan_table_enrollment_suppressed_imputed_to_5(landscape_df, benefits_df, cpsc_df):
    table = plan_attributes.build_plan_table(2024, landscape_df, benefits_df, cpsc_df)
    idx = table.set_index("plan_key")
    assert idx.loc["H0002-001", "enrollment_2024_03"] == pytest.approx(5.0)
    assert idx.loc["H0001-001", "enrollment_2024_03"] == pytest.approx(400.0)


def test_build_plan_table_sorted_by_plan_key(landscape_df, benefits_df, cpsc_df):
    table = plan_attributes.build_plan_table(2024, landscape_df, benefits_df, cpsc_df)
    assert table["plan_key"].tolist() == sorted(table["plan_key"].tolist())


def test_build_plan_table_no_moop_nulls_after_impute(landscape_df, benefits_df, cpsc_df):
    landscape_df = landscape_df.copy()
    landscape_df.loc[0, "moop_inn"] = None
    table = plan_attributes.build_plan_table(2024, landscape_df, benefits_df, cpsc_df)
    assert not table["moop_inn"].isna().any()


def test_build_plan_table_year_field(landscape_df, benefits_df, cpsc_df):
    table = plan_attributes.build_plan_table(2025, landscape_df, benefits_df, cpsc_df)
    assert (table["year"] == 2025).all()
    assert "enrollment_2025_03" in table.columns


# --- integration: real data ----------------------------------------------------


def _interim_available() -> bool:
    required = [
        "landscape_2024.parquet",
        "landscape_2025.parquet",
        "benefits_2024.parquet",
        "benefits_2025.parquet",
        "cpsc_2024_03.parquet",
        "cpsc_2025_03.parquet",
        "plan_crosswalk_2024_2025.parquet",
    ]
    return all((settings.INTERIM_DIR / name).exists() for name in required)


@pytest.fixture(scope="module")
def built_results():
    if not _interim_available():
        pytest.skip("Phase 1 interim data not present; run `make ingest` first")
    return plan_attributes.build_all()


@pytest.mark.integration
def test_real_2024_plan_count(built_results):
    assert len(built_results[2024]["plans"]) == 93


@pytest.mark.integration
def test_real_2025_plan_count(built_results):
    assert len(built_results[2025]["plans"]) == 94


@pytest.mark.integration
def test_real_moop_fully_populated_both_years(built_results):
    for year in (2024, 2025):
        for plan in built_results[year]["plans"]:
            assert plan["moop_inn"] is not None
            assert plan["moop_inn"] > 0


@pytest.mark.integration
def test_real_moop_imputation_method_counts(built_results):
    notes = built_results[2024]["metadata"]["imputation_notes"]["moop"]
    assert notes["method_counts"]["crosswalk_backfill"] == 26
    assert notes["method_counts"]["type_median"] == 3
    assert notes["null_count_source"] == 29


@pytest.mark.integration
def test_real_schema_validates(built_results):
    PlansFile2024.model_validate(built_results[2024])
    PlansFile2025.model_validate(built_results[2025])


@pytest.mark.integration
def test_real_deterministic_build_is_byte_identical(tmp_path):
    if not _interim_available():
        pytest.skip("Phase 1 interim data not present; run `make ingest` first")
    out_dir_a = tmp_path / "a"
    out_dir_b = tmp_path / "b"
    plan_attributes.build_all(output_dir=out_dir_a)
    plan_attributes.build_all(output_dir=out_dir_b)
    for name in ("plans_2024.json", "plans_2025.json"):
        assert (out_dir_a / name).read_bytes() == (out_dir_b / name).read_bytes()


@pytest.mark.integration
def test_real_output_files_written_to_processed_dir():
    if not _interim_available():
        pytest.skip("Phase 1 interim data not present; run `make ingest` first")
    plan_attributes.build_all()
    for name in ("plans_2024.json", "plans_2025.json"):
        path = settings.PROCESSED_DIR / name
        assert path.exists()
        on_disk = json.loads(path.read_text())
        assert "plans" in on_disk
        assert "metadata" in on_disk
