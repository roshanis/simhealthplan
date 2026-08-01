"""Tests for pipeline/export/golden_fixture.py -- the Python <-> TypeScript
choice-model golden parity fixture (shared/golden/parity_fixture.json).

Two guarantees this file pins down:

  1. Regenerating the fixture from the real committed artifacts
     (data/processed/{coefficients,archetypes,plans_2025}.json) reproduces
     the committed file byte-identically -- deterministic generation, no
     hidden randomness, no dict/set-ordering drift.
  2. Replaying each fixture case's OWN recorded inputs (the committed
     `plans` array + that case's `plan_patches` / `plan_subset` /
     `archetype` / the fixture's `base_coefficients`) through the frozen
     choice_model.{choice_sets,utility} modules reproduces that case's
     recorded `expected_probabilities` to within 1e-12 absolute tolerance.
     This uses ONLY fields a TypeScript port also has access to (not
     golden_fixture.py's internal case-building helpers) -- it's the same
     contract app/tests/parity.test.ts's TS replay relies on.
"""

from __future__ import annotations

import json

import pytest

from choice_model import choice_sets, utility
from config.settings import settings
from export import golden_fixture

FIXTURE_PATH = settings.SHARED_GOLDEN_DIR / "parity_fixture.json"

EXPECTED_SEGMENTS = {"mixed", "price_sensitive", "benefit_maximizer", "brand_loyal", "health_status_driven"}


@pytest.fixture(scope="module")
def committed_fixture() -> dict:
    if not FIXTURE_PATH.exists():
        pytest.skip(f"{FIXTURE_PATH} not present; run `cd pipeline && uv run python -m export.golden_fixture` first")
    return json.loads(FIXTURE_PATH.read_text())


# --- fixture exists / regenerates byte-identically ------------------------------


def test_fixture_file_exists():
    assert FIXTURE_PATH.exists(), f"missing {FIXTURE_PATH}; run `cd pipeline && uv run python -m export.golden_fixture`"


def test_regenerating_fixture_is_byte_identical(committed_fixture):
    regenerated = golden_fixture.build_fixture()
    regenerated_text = json.dumps(regenerated, indent=2, sort_keys=True) + "\n"
    committed_text = FIXTURE_PATH.read_text()
    assert regenerated_text == committed_text


# --- fixture inventory ------------------------------------------------------------


def test_fixture_has_expected_case_count(committed_fixture):
    assert committed_fixture["metadata"]["n_cases"] == len(committed_fixture["cases"]) == 17
    assert committed_fixture["metadata"]["n_plans"] == len(committed_fixture["plans"]) == 94


def test_fixture_case_kinds_cover_real_synthetic_and_scenario(committed_fixture):
    kinds = [case["kind"] for case in committed_fixture["cases"]]
    assert set(kinds) == {"real", "synthetic", "scenario"}
    assert kinds.count("real") == 12
    assert kinds.count("synthetic") == 3
    assert kinds.count("scenario") == 2


def test_fixture_covers_all_five_attitude_segments(committed_fixture):
    segments = {case["archetype"]["attitude_segment"] for case in committed_fixture["cases"]}
    assert segments == EXPECTED_SEGMENTS


def test_fixture_covers_dual_and_non_dual_and_85_plus(committed_fixture):
    duals = {case["archetype"]["dual_proxy"] for case in committed_fixture["cases"]}
    assert duals == {True, False}
    ages = {case["archetype"]["age_band"] for case in committed_fixture["cases"]}
    assert "85+" in ages


def test_case_ids_are_unique(committed_fixture):
    case_ids = [case["case_id"] for case in committed_fixture["cases"]]
    assert len(case_ids) == len(set(case_ids))


def test_synthetic_edge_cases_present(committed_fixture):
    synthetic_ids = {case["archetype"]["id"] for case in committed_fixture["cases"] if case["kind"] == "synthetic"}
    assert synthetic_ids == {
        "synthetic_zero_prior_mass",
        "synthetic_all_mass_outside",
        "synthetic_single_plan_eligible",
    }
    by_id = {case["archetype"]["id"]: case for case in committed_fixture["cases"] if case["kind"] == "synthetic"}
    assert by_id["synthetic_zero_prior_mass"]["archetype"]["prior_plan_year1"] == {}
    assert by_id["synthetic_all_mass_outside"]["archetype"]["prior_plan_year1"] == {
        committed_fixture["metadata"]["outside_option_key"]: 1.0
    }
    assert len(by_id["synthetic_single_plan_eligible"]["plan_subset"]) == 1


def test_scenario_variants_patch_the_largest_plan(committed_fixture):
    scenario_cases = [case for case in committed_fixture["cases"] if case["kind"] == "scenario"]
    assert len(scenario_cases) == 2
    patched_plan_keys = {next(iter(case["plan_patches"])) for case in scenario_cases}
    assert len(patched_plan_keys) == 1  # both variants patch the same (largest) plan
    fields_patched = {field for case in scenario_cases for patch in case["plan_patches"].values() for field in patch}
    assert fields_patched == {"premium_total", "has_comprehensive_dental"}


# --- self-check: fixture is reproducible from its own recorded fields -----------


def test_every_case_probabilities_sum_to_one(committed_fixture):
    for case in committed_fixture["cases"]:
        total = sum(case["expected_probabilities"].values())
        assert total == pytest.approx(1.0, abs=1e-9), case["case_id"]


def test_each_case_self_check_reproduces_expected_probabilities(committed_fixture):
    """Replay every case's own recorded inputs through choice_sets + utility
    and check we reproduce its recorded expected_probabilities within 1e-12
    absolute tolerance -- i.e. the fixture is self-consistent using only the
    fields a TS port also has (base_coefficients, plans, plan_patches,
    plan_subset, archetype), not golden_fixture.py's internal helpers."""
    base_coefficients = committed_fixture["base_coefficients"]
    outside_key = committed_fixture["metadata"]["outside_option_key"]

    for case in committed_fixture["cases"]:
        case_plans = golden_fixture.resolve_case_plans(
            committed_fixture["plans"], case["plan_patches"], case["plan_subset"]
        )
        archetype = case["archetype"]

        eligible = choice_sets.eligible_plans(archetype, case_plans)
        renormalized_prior = choice_sets.renormalize_prior_plan(
            archetype.get("prior_plan_year1", {}), archetype, case_plans, outside_key
        )
        actual = utility.choice_probabilities(
            base_coefficients, archetype["attitude_segment"], eligible, renormalized_prior, outside_key
        )

        expected = case["expected_probabilities"]
        assert set(actual.keys()) == set(expected.keys()), case["case_id"]
        for key, expected_value in expected.items():
            assert actual[key] == pytest.approx(expected_value, abs=1e-12), f"{case['case_id']} / {key}"
