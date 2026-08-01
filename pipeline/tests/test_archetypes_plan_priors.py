"""Tests for archetypes/plan_priors.py — Year-1 prior-plan distributions.

TDD against small synthetic landscape/benefits/CPSC-shaped DataFrames. The
integration test exercises the real 2024 interim files.
"""

from __future__ import annotations

import pandas as pd
import pytest

from archetypes import plan_priors
from config.settings import settings


@pytest.fixture
def landscape_df():
    return pd.DataFrame(
        [
            {"contract_id": "H0001", "plan_id": "001", "snp_type": "Not Applicable", "premium_part_c": 0.0},
            {"contract_id": "H0001", "plan_id": "002", "snp_type": "Not Applicable", "premium_part_c": 35.0},
            {"contract_id": "H0002", "plan_id": "001", "snp_type": "Dual-Eligible", "premium_part_c": 0.0},
            {"contract_id": "H0003", "plan_id": "001", "snp_type": "Chronic or Disabling Condition", "premium_part_c": 0.0},
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
                "has_hearing_aids": True,
                "has_otc_or_flex": True,
            },
            {
                "contract_id": "H0001",
                "plan_id": "002",
                "has_comprehensive_dental": False,
                "has_vision": False,
                "has_hearing_aids": False,
                "has_otc_or_flex": False,
            },
            {
                "contract_id": "H0002",
                "plan_id": "001",
                "has_comprehensive_dental": True,
                "has_vision": False,
                "has_hearing_aids": False,
                "has_otc_or_flex": False,
            },
            {
                "contract_id": "H0003",
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
            {"contract_id": "H0001", "plan_id": "002", "enrollment": pd.NA, "suppressed": True},
            {"contract_id": "H0002", "plan_id": "001", "enrollment": 100, "suppressed": False},
            {"contract_id": "H0003", "plan_id": "001", "enrollment": 50, "suppressed": False},
            # a plan outside the landscape universe -- should be ignored.
            {"contract_id": "H9999", "plan_id": "999", "enrollment": 20, "suppressed": False},
        ]
    )


@pytest.fixture
def archetypes_df():
    return pd.DataFrame(
        [
            {"archetype_id": "a1", "weight": 300.0, "attitude_segment": "price_sensitive", "dual_proxy": False},
            {"archetype_id": "a2", "weight": 200.0, "attitude_segment": "benefit_maximizer", "dual_proxy": False},
            {"archetype_id": "a3", "weight": 150.0, "attitude_segment": "brand_loyal", "dual_proxy": True},
            {"archetype_id": "a4", "weight": 350.0, "attitude_segment": "health_status_driven", "dual_proxy": False},
        ]
    )


def test_plan_key_format():
    assert plan_priors.plan_key("H0001", "001") == "H0001-001"


def test_build_plan_universe_flags_dsnp_and_richness(landscape_df, benefits_df):
    universe = plan_priors.build_plan_universe(landscape_df, benefits_df)
    assert len(universe) == 4
    by_key = universe.set_index("plan_key")
    assert by_key.loc["H0002-001", "is_dsnp"] == True  # noqa: E712
    assert by_key.loc["H0001-001", "is_dsnp"] == False  # noqa: E712
    assert by_key.loc["H0003-001", "is_dsnp"] == False  # noqa: E712 (C-SNP, not D-SNP)
    assert by_key.loc["H0001-001", "is_zero_premium"] == True  # noqa: E712
    assert by_key.loc["H0001-002", "is_zero_premium"] == False  # noqa: E712
    assert by_key.loc["H0001-001", "rich_benefit_count"] == 4
    assert by_key.loc["H0001-002", "rich_benefit_count"] == 0


def test_cpsc_plan_targets_imputes_suppressed_and_adds_outside(landscape_df, benefits_df, cpsc_df):
    universe = plan_priors.build_plan_universe(landscape_df, benefits_df)
    targets = plan_priors.cpsc_plan_targets(cpsc_df, universe, eligibles_total=1000.0, impute_suppressed=5)

    assert targets["H0001-001"] == 400
    assert targets["H0001-002"] == 5  # imputed
    assert targets["H0002-001"] == 100
    assert targets["H0003-001"] == 50
    assert "H9999-999" not in targets.index  # outside the landscape universe

    landscape_total = 400 + 5 + 100 + 50
    assert targets[plan_priors.OUTSIDE_PLAN_KEY] == pytest.approx(1000.0 - landscape_total)
    assert targets.sum() == pytest.approx(1000.0)


def test_build_seed_matrix_hard_zeros_dsnp_for_non_dual(landscape_df, benefits_df, archetypes_df):
    universe = plan_priors.build_plan_universe(landscape_df, benefits_df)
    seed = plan_priors.build_seed_matrix(archetypes_df, universe)

    non_dual = archetypes_df[~archetypes_df["dual_proxy"]]["archetype_id"]
    for aid in non_dual:
        assert seed.loc[aid, "H0002-001"] == 0.0

    dual = archetypes_df[archetypes_df["dual_proxy"]]["archetype_id"]
    for aid in dual:
        assert seed.loc[aid, "H0002-001"] > 0.0


def test_build_seed_matrix_tilts_price_sensitive_toward_zero_premium(landscape_df, benefits_df, archetypes_df):
    universe = plan_priors.build_plan_universe(landscape_df, benefits_df)
    seed = plan_priors.build_seed_matrix(archetypes_df, universe)
    # a1 is price_sensitive: $0-premium plan (H0001-001) should out-seed the
    # non-zero-premium plan (H0001-002) more than for a non-price-sensitive
    # archetype with otherwise-equal plan attributes.
    a1_ratio = seed.loc["a1", "H0001-001"] / seed.loc["a1", "H0001-002"]
    a4_ratio = seed.loc["a4", "H0001-001"] / seed.loc["a4", "H0001-002"]
    assert a1_ratio > a4_ratio


def test_build_seed_matrix_tilts_benefit_maximizer_toward_rich_benefits(landscape_df, benefits_df, archetypes_df):
    universe = plan_priors.build_plan_universe(landscape_df, benefits_df)
    seed = plan_priors.build_seed_matrix(archetypes_df, universe)
    # a2 is benefit_maximizer: H0001-001 (4 rich benefits) should out-seed
    # H0001-002 (0 rich benefits) more than for a1 (price_sensitive).
    a2_ratio = seed.loc["a2", "H0001-001"] / seed.loc["a2", "H0001-002"]
    a3_ratio = seed.loc["a3", "H0001-001"] / seed.loc["a3", "H0001-002"]
    assert a2_ratio > a3_ratio


def test_fit_plan_priors_probabilities_sum_to_one_and_reproduce_targets(
    landscape_df, benefits_df, cpsc_df, archetypes_df
):
    universe = plan_priors.build_plan_universe(landscape_df, benefits_df)
    eligibles_total = archetypes_df["weight"].sum()
    targets = plan_priors.cpsc_plan_targets(cpsc_df, universe, eligibles_total=eligibles_total)

    priors, iterations = plan_priors.fit_plan_priors(archetypes_df, universe, targets, tol=1e-10)

    assert iterations >= 1
    for aid, dist in priors.items():
        assert sum(dist.values()) == pytest.approx(1.0, abs=1e-8)

    # Archetype-weighted column sums reproduce the CPSC targets exactly (by
    # IPF construction).
    weight_by_id = archetypes_df.set_index("archetype_id")["weight"]
    for plan in targets.index:
        recon = sum(weight_by_id[aid] * priors[aid].get(plan, 0.0) for aid in priors)
        assert recon == pytest.approx(targets[plan], abs=1e-6)

    # Hard D-SNP constraint holds after fitting too.
    non_dual = archetypes_df[~archetypes_df["dual_proxy"]]["archetype_id"]
    for aid in non_dual:
        assert priors[aid]["H0002-001"] == pytest.approx(0.0, abs=1e-12)


@pytest.mark.integration
def test_real_plan_priors_end_to_end():
    landscape_path = settings.INTERIM_DIR / "landscape_2024.parquet"
    benefits_path = settings.INTERIM_DIR / "benefits_2024.parquet"
    cpsc_path = settings.INTERIM_DIR / "cpsc_2024_03.parquet"
    penetration_path = settings.INTERIM_DIR / "penetration_2024_03.parquet"
    for p in (landscape_path, benefits_path, cpsc_path, penetration_path):
        if not p.exists():
            pytest.skip(f"{p} not present; run `make ingest` first")

    landscape = pd.read_parquet(landscape_path)
    benefits = pd.read_parquet(benefits_path)
    cpsc = pd.read_parquet(cpsc_path)
    eligibles_total = float(pd.read_parquet(penetration_path)["eligibles"].iloc[0])

    universe = plan_priors.build_plan_universe(landscape, benefits)
    assert universe["is_dsnp"].sum() == 10  # matches landscape_2024 snp_type == "Dual-Eligible" count

    targets = plan_priors.cpsc_plan_targets(cpsc, universe, eligibles_total=eligibles_total)
    assert targets.sum() == pytest.approx(eligibles_total)
    assert (targets >= 0).all()
