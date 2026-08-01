"""Tests for llm/persona_prompts.py — Phase 4 consideration-set construction
and the CHOICE / BACKSTORY structured-output prompt builders.
"""

from __future__ import annotations

import json

import pytest

from choice_model import choice_sets, predict
from config.settings import settings
from llm import persona_prompts

OUTSIDE2 = predict.OUTSIDE_KEY_YEAR2
OUTSIDE1 = predict.OUTSIDE_KEY_YEAR1


def _plan(key, snp_type="Not Applicable", enrollment=10.0, **overrides):
    base = {
        "plan_key": key,
        "plan_name": f"Plan {key}",
        "plan_type": "HMO",
        "snp_type": snp_type,
        "premium_total": 20.0,
        "moop_inn": 5000.0,
        "star_rating": 4.0,
        "has_comprehensive_dental": True,
        "has_vision": True,
        "has_hearing_aids": False,
        "has_otc_or_flex": True,
        "enrollment_2025_03": enrollment,
    }
    base.update(overrides)
    return base


def _archetype(**overrides):
    base = {
        "id": "a1",
        "age_band": "70-74",
        "income_tier": "middle",
        "dual_proxy": False,
        "attitude_segment": "mixed",
        "race_eth": "hispanic",
        "traits": ["values simplicity", "middle income"],
        "prior_plan_year1": {},
    }
    base.update(overrides)
    return base


# --- build_consideration_set ----------------------------------------------------


def test_consideration_set_size_capped_at_k():
    eligible = [f"P{i}" for i in range(20)]
    plans_2025 = [_plan(k, enrollment=float(i)) for i, k in enumerate(eligible)]
    logit_probs = {k: 1.0 / len(eligible) for k in eligible}
    prior = {}

    result = persona_prompts.build_consideration_set(eligible, logit_probs, prior, plans_2025, OUTSIDE2, k=8)

    assert len(result) == 8
    assert len(set(result)) == 8  # dedup: no duplicates


def test_consideration_set_never_exceeds_eligible_pool():
    eligible = ["P1", "P2", "P3"]
    plans_2025 = [_plan(k) for k in eligible]
    result = persona_prompts.build_consideration_set(eligible, {}, {}, plans_2025, OUTSIDE2, k=8)
    assert set(result) <= set(eligible)
    assert len(result) <= 3


def test_consideration_set_excludes_outside_key_even_if_passed_in_eligible():
    eligible = ["P1", "P2", OUTSIDE2]
    plans_2025 = [_plan("P1"), _plan("P2")]
    result = persona_prompts.build_consideration_set(eligible, {}, {}, plans_2025, OUTSIDE2, k=8)
    assert OUTSIDE2 not in result


def test_consideration_set_includes_top_prior_mass_plan():
    eligible = ["P1", "P2", "P3"]
    plans_2025 = [_plan(k) for k in eligible]
    prior = {"P2": 0.8, "P1": 0.05}
    result = persona_prompts.build_consideration_set(eligible, {}, prior, plans_2025, OUTSIDE2, k=8)
    assert "P2" in result


def test_consideration_set_includes_top_2_enrollment_plans():
    eligible = ["P1", "P2", "P3", "P4"]
    plans_2025 = [
        _plan("P1", enrollment=1000.0),
        _plan("P2", enrollment=5.0),
        _plan("P3", enrollment=900.0),
        _plan("P4", enrollment=3.0),
    ]
    result = persona_prompts.build_consideration_set(eligible, {}, {}, plans_2025, OUTSIDE2, k=8)
    assert "P1" in result
    assert "P3" in result


def test_consideration_set_includes_top_logit_prob_plans():
    eligible = ["P1", "P2", "P3", "P4", "P5"]
    plans_2025 = [
        _plan("P1", enrollment=1000.0),  # top-enrollment slot 1
        _plan("P2", enrollment=5.0),  # NOT top enrollment, but highest logit prob
        _plan("P3", enrollment=900.0),  # top-enrollment slot 2
        _plan("P4", enrollment=4.0),
        _plan("P5", enrollment=3.0),
    ]
    logit_probs = {"P1": 0.1, "P2": 0.6, "P3": 0.1, "P4": 0.1, "P5": 0.1}
    result = persona_prompts.build_consideration_set(eligible, logit_probs, {}, plans_2025, OUTSIDE2, k=3)
    # k=3: 2 enrollment-anchor slots (P1, P3) filled first, then the highest
    # remaining logit-probability plan (P2) fills the last slot.
    assert result == ["P1", "P3", "P2"]


def test_consideration_set_deterministic_tie_break_by_plan_key():
    eligible = ["Z1", "A1"]
    plans_2025 = [_plan("Z1", enrollment=5.0), _plan("A1", enrollment=5.0)]
    result_a = persona_prompts.build_consideration_set(eligible, {}, {}, plans_2025, OUTSIDE2, k=8)
    result_b = persona_prompts.build_consideration_set(eligible, {}, {}, plans_2025, OUTSIDE2, k=8)
    assert result_a == result_b
    assert result_a[0] == "A1"  # alphabetically-first tie-break


def test_consideration_set_dsnp_excluded_for_non_dual_archetype_end_to_end():
    """The required D-SNP-exclusion test: build the eligible set the real
    way (choice_sets.eligible_plans for a non-dual archetype), and confirm
    the consideration set built from it can never contain the D-SNP plan --
    even when that D-SNP plan would otherwise dominate on prior mass,
    enrollment, and logit probability."""
    plans_2025 = [
        _plan("DSNP1", snp_type="Dual-Eligible", enrollment=99999.0),
        _plan("HMO1", enrollment=10.0),
        _plan("HMO2", enrollment=5.0),
    ]
    non_dual = {"dual_proxy": False, "age_band": "70-74", "attitude_segment": "mixed"}
    eligible_plans = choice_sets.eligible_plans(non_dual, plans_2025)
    eligible_keys = [p["plan_key"] for p in eligible_plans]
    assert "DSNP1" not in eligible_keys

    logit_probs = {"DSNP1": 0.9, "HMO1": 0.05, "HMO2": 0.05}
    prior = {"DSNP1": 0.9, "HMO1": 0.05}

    result = persona_prompts.build_consideration_set(eligible_keys, logit_probs, prior, plans_2025, OUTSIDE2, k=8)

    assert "DSNP1" not in result
    assert set(result) <= {"HMO1", "HMO2"}


def test_consideration_set_dsnp_included_for_dual_archetype():
    plans_2025 = [_plan("DSNP1", snp_type="Dual-Eligible", enrollment=100.0), _plan("HMO1", enrollment=10.0)]
    dual = {"dual_proxy": True, "age_band": "70-74", "attitude_segment": "mixed"}
    eligible_plans = choice_sets.eligible_plans(dual, plans_2025)
    eligible_keys = [p["plan_key"] for p in eligible_plans]

    result = persona_prompts.build_consideration_set(eligible_keys, {}, {}, plans_2025, OUTSIDE2, k=8)

    assert "DSNP1" in result


# --- format_current_coverage_summary ---------------------------------------------


def test_current_coverage_summary_includes_outside_share_even_if_not_top_n():
    prior = {"P1": 0.9, OUTSIDE1: 0.02, "P2": 0.05, "P3": 0.03}
    plans_2024_by_key = {"P1": {"plan_name": "Plan One"}, "P2": {"plan_name": "Plan Two"}, "P3": {"plan_name": "Plan Three"}}
    summary = persona_prompts.format_current_coverage_summary(prior, plans_2024_by_key, OUTSIDE1, top_n=1)
    assert "Plan One" in summary
    assert "2.0%" in summary  # outside share explicitly stated even though it's ranked last


def test_current_coverage_summary_handles_all_outside():
    prior = {OUTSIDE1: 1.0}
    summary = persona_prompts.format_current_coverage_summary(prior, {}, OUTSIDE1)
    assert "100.0%" in summary


# --- build_choice_prompt ---------------------------------------------------------


def _plans_by_key(plans):
    return {p["plan_key"]: p for p in plans}


def test_build_choice_prompt_shape_and_alternative_keys():
    archetype = _archetype(prior_plan_year1={"P1": 0.5, OUTSIDE1: 0.5})
    plans_2025 = [_plan("P1"), _plan("P2")]
    plans_2024_by_key = {"P1": {"plan_name": "Plan One (2024)"}}
    consideration = ["P1", "P2"]

    spec = persona_prompts.build_choice_prompt(archetype, plans_2024_by_key, _plans_by_key(plans_2025), consideration, OUTSIDE1, OUTSIDE2)

    assert spec["prompt_key"] == "y2_choice_v1"
    assert spec["schema_version"] == "v1"
    assert spec["alternative_keys"] == ["P1", "P2", OUTSIDE2]
    assert archetype["id"] in spec["user"]
    assert "P1" in spec["user"] and "P2" in spec["user"] and OUTSIDE2 in spec["user"]

    schema = spec["response_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"ranked_plan_keys", "switching_propensity", "rationale"}
    assert schema["properties"]["ranked_plan_keys"]["items"]["enum"] == ["P1", "P2", OUTSIDE2]
    assert schema["properties"]["switching_propensity"]["minimum"] == 0
    assert schema["properties"]["switching_propensity"]["maximum"] == 1


def test_build_choice_prompt_is_pure_and_deterministic():
    archetype = _archetype(prior_plan_year1={"P1": 1.0})
    plans_2025 = [_plan("P1")]
    spec_a = persona_prompts.build_choice_prompt(archetype, {}, _plans_by_key(plans_2025), ["P1"], OUTSIDE1, OUTSIDE2)
    spec_b = persona_prompts.build_choice_prompt(archetype, {}, _plans_by_key(plans_2025), ["P1"], OUTSIDE1, OUTSIDE2)
    assert spec_a == spec_b


def test_choice_response_schema_strict_shape():
    schema = persona_prompts.choice_response_schema(["A", "B", OUTSIDE2])
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "minItems" not in schema["properties"]["ranked_plan_keys"]
    assert "maxItems" not in schema["properties"]["ranked_plan_keys"]


# --- build_backstory_prompt -------------------------------------------------------


def test_build_backstory_prompt_shape():
    archetype = _archetype()
    spec = persona_prompts.build_backstory_prompt(archetype)

    assert spec["prompt_key"] == "backstory_v1"
    assert spec["schema_version"] == "v1"
    schema = spec["response_schema"]
    assert set(schema["required"]) == {"name", "backstory"}
    assert schema["additionalProperties"] is False
    assert archetype["id"] in spec["user"]


def test_build_backstory_prompt_instructs_against_mechanical_race_to_name_derivation():
    spec = persona_prompts.build_backstory_prompt(_archetype())
    system_lower = spec["system"].lower()
    assert "stereotyp" in system_lower
    assert "race" in system_lower or "ethnicity" in system_lower
    assert "mechanically" in system_lower or "not derive" in system_lower or "do not" in system_lower


def test_build_backstory_prompt_instructs_fictional_not_real_person():
    spec = persona_prompts.build_backstory_prompt(_archetype())
    assert "fictional" in spec["system"].lower()
    assert "not a real person" in spec["system"].lower()


def test_build_backstory_prompt_grounded_in_traits_and_demographics():
    archetype = _archetype(age_band="85+", income_tier="low_dual_proxy", traits=["oldest-old", "cost-sensitive"])
    spec = persona_prompts.build_backstory_prompt(archetype)
    assert "85+" in spec["user"]
    assert "low_dual_proxy" in spec["user"]
    assert "oldest-old" in spec["user"]


def test_build_backstory_prompt_handles_mixed_race_eth_catch_all():
    archetype = _archetype(race_eth="mixed")
    spec = persona_prompts.build_backstory_prompt(archetype)
    assert "catch-all" in spec["user"].lower() or "aggregated" in spec["user"].lower()


# --- real-data integration: consideration set across all 80 archetypes -----------


def _real_data_available() -> bool:
    return (
        (settings.PROCESSED_DIR / "archetypes.json").exists()
        and (settings.PROCESSED_DIR / "plans_2025.json").exists()
        and (settings.PROCESSED_DIR / "coefficients.json").exists()
        and (settings.INTERIM_DIR / "plan_crosswalk_2024_2025.parquet").exists()
    )


@pytest.mark.integration
def test_real_consideration_sets_never_leak_dsnp_to_non_dual_archetypes():
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")

    archetypes = json.loads((settings.PROCESSED_DIR / "archetypes.json").read_text())["archetypes"]
    plans_2025 = json.loads((settings.PROCESSED_DIR / "plans_2025.json").read_text())["plans"]
    coefficients = json.loads((settings.PROCESSED_DIR / "coefficients.json").read_text())
    crosswalk_map = predict.load_crosswalk_map()

    dsnp_keys = {p["plan_key"] for p in plans_2025 if p["snp_type"] == "Dual-Eligible"}
    assert dsnp_keys  # sanity: the real 2025 landscape does have D-SNP plans

    logit_result = predict.predict_all(archetypes, plans_2025, coefficients["base_coefficients"], crosswalk_map)

    checked_non_dual = 0
    for archetype in archetypes:
        per = logit_result["per_archetype"][archetype["id"]]
        consideration = persona_prompts.build_consideration_set(
            per["eligible_plan_keys"], per["probs"], per["renormalized_prior"], plans_2025, predict.OUTSIDE_KEY_YEAR2
        )
        assert len(consideration) <= 8
        assert len(set(consideration)) == len(consideration)
        if not archetype["dual_proxy"]:
            checked_non_dual += 1
            assert not (set(consideration) & dsnp_keys), f"{archetype['id']} consideration set leaked a D-SNP plan"

    assert checked_non_dual > 0
