"""Master acceptance tests for archetypes/build_archetypes.py (Phase 2 deliverable).

All tests here are integration tests against the real Phase 1 interim data
(data/interim/*.parquet) -- there's no meaningful way to unit-test "the
whole pipeline produces a valid archetypes.json" against synthetic stubs
without just re-testing the already-unit-tested submodules. Each submodule
(acs_marginals, mcbs_segments, ipf, cells, plan_priors, traits) has its own
dedicated unit tests.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from archetypes import build_archetypes
from archetypes.constants import ATTITUDE_SEGMENTS
from config.settings import settings

pytestmark = pytest.mark.integration


def _inputs_available() -> bool:
    required = [
        "acs_maricopa.parquet",
        "mcbs_subset.parquet",
        "landscape_2024.parquet",
        "benefits_2024.parquet",
        "cpsc_2024_03.parquet",
        "penetration_2024_03.parquet",
    ]
    return all((settings.INTERIM_DIR / name).exists() for name in required)


@pytest.fixture(scope="module")
def result():
    if not _inputs_available():
        pytest.skip("Phase 1 interim data not present; run `make ingest` first")
    return build_archetypes.build()


def test_archetype_count_in_range(result):
    assert 30 <= len(result["archetypes"]) <= 80
    assert result["metadata"]["archetype_count"] == len(result["archetypes"])


def test_weights_sum_to_eligibles_total_and_all_positive(result):
    total = sum(a["weight"] for a in result["archetypes"])
    expected = result["metadata"]["population_total"]
    assert total == pytest.approx(expected, rel=1e-6)
    assert all(a["weight"] > 0 for a in result["archetypes"])


def test_prior_plan_year1_reproduces_cpsc_shares_within_tolerance(result):
    archetypes = result["archetypes"]
    weight_by_id = {a["id"]: a["weight"] for a in archetypes}

    # Reconstruct archetype-weighted column sums for every plan key seen.
    all_plan_keys = set()
    for a in archetypes:
        all_plan_keys.update(a["prior_plan_year1"].keys())
    all_plan_keys.discard("other_or_no_ma_2024")

    recon = {
        pk: sum(weight_by_id[a["id"]] * a["prior_plan_year1"].get(pk, 0.0) for a in archetypes) for pk in all_plan_keys
    }

    landscape = pd.read_parquet(settings.INTERIM_DIR / "landscape_2024.parquet")
    benefits = pd.read_parquet(settings.INTERIM_DIR / "benefits_2024.parquet")
    cpsc = pd.read_parquet(settings.INTERIM_DIR / "cpsc_2024_03.parquet")

    from archetypes import plan_priors

    universe = plan_priors.build_plan_universe(landscape, benefits)
    eligibles_total = result["metadata"]["population_total"]
    targets = plan_priors.cpsc_plan_targets(cpsc, universe, eligibles_total=eligibles_total)

    landscape_keys = [k for k in targets.index if k != plan_priors.OUTSIDE_PLAN_KEY]
    landscape_total = targets[landscape_keys].sum()

    errs = []
    weights = []
    for pk in landscape_keys:
        actual_share = targets[pk] / landscape_total
        recon_share = recon.get(pk, 0.0) / landscape_total
        errs.append(abs(actual_share - recon_share))
        weights.append(targets[pk])

    errs = pd.Series(errs)
    weights = pd.Series(weights)
    size_weighted_mae_pp = (errs * weights).sum() / weights.sum() * 100
    assert size_weighted_mae_pp < 1.0
    assert size_weighted_mae_pp < 0.1  # should be ~0 by IPF construction


def test_zero_dsnp_mass_on_non_dual_archetypes(result):
    landscape = pd.read_parquet(settings.INTERIM_DIR / "landscape_2024.parquet")
    dsnp_keys = {
        f"{row.contract_id}-{row.plan_id}" for row in landscape.itertuples() if row.snp_type == "Dual-Eligible"
    }
    assert dsnp_keys, "expected at least one D-SNP plan in landscape_2024"

    for a in result["archetypes"]:
        if not a["dual_proxy"]:
            for pk in dsnp_keys:
                assert a["prior_plan_year1"].get(pk, 0.0) == 0.0


def test_deterministic_build_is_byte_identical(tmp_path):
    if not _inputs_available():
        pytest.skip("Phase 1 interim data not present; run `make ingest` first")
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    build_archetypes.build(output_path=path_a)
    build_archetypes.build(output_path=path_b)
    assert path_a.read_bytes() == path_b.read_bytes()


def test_segment_probabilities_and_national_shares(result):
    national = result["metadata"]["mcbs_segmentation"]["national_shares"]
    assert set(national) == set(ATTITUDE_SEGMENTS)
    assert sum(national.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(v > 0 for v in national.values())


def test_output_file_written_and_matches_returned_result():
    if not _inputs_available():
        pytest.skip("Phase 1 interim data not present; run `make ingest` first")
    build_archetypes.build()
    output_path = settings.PROCESSED_DIR / "archetypes.json"
    assert output_path.exists()
    on_disk = json.loads(output_path.read_text())
    assert "archetypes" in on_disk
    assert "metadata" in on_disk
    assert 30 <= len(on_disk["archetypes"]) <= 80
