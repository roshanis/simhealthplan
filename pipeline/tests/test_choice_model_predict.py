"""Tests for choice_model/predict.py — Phase 4 Year-2 logit baseline.

Unit tests exercise the crosswalk mapping + per-archetype prediction against
small synthetic fixtures. The real-data integration tests validate shape,
determinism, and the "terminated plans carry zero inertia" property against
the real committed archetypes.json / plans_2025.json / coefficients.json /
plan_crosswalk_2024_2025.parquet.
"""

from __future__ import annotations

import json

import pytest

from choice_model import choice_sets, predict, utility
from config.settings import settings

OUTSIDE1 = predict.OUTSIDE_KEY_YEAR1
OUTSIDE2 = predict.OUTSIDE_KEY_YEAR2


# --- crosswalk_map_from_rows --------------------------------------------------


def _row(old_c, old_p, new_c, new_p, disposition):
    return {
        "old_contract_id": old_c,
        "old_plan_id": old_p,
        "new_contract_id": new_c,
        "new_plan_id": new_p,
        "disposition": disposition,
    }


def test_crosswalk_map_renewed_same_key():
    rows = [_row("H0001", "001", "H0001", "001", "renewed")]
    mapping = predict.crosswalk_map_from_rows(rows)
    assert mapping["H0001-001"] == {"disposition": "renewed", "new_plan_key": "H0001-001"}


def test_crosswalk_map_renumbered_different_key():
    rows = [_row("H0001", "052", "H0001", "074", "renumbered")]
    mapping = predict.crosswalk_map_from_rows(rows)
    assert mapping["H0001-052"]["new_plan_key"] == "H0001-074"
    assert mapping["H0001-052"]["disposition"] == "renumbered"


def test_crosswalk_map_consolidated_multiple_old_to_one_new():
    rows = [
        _row("H0001", "062", "H0001", "063", "consolidated"),
        _row("H0001", "063", "H0001", "063", "consolidated"),
    ]
    mapping = predict.crosswalk_map_from_rows(rows)
    assert mapping["H0001-062"]["new_plan_key"] == "H0001-063"
    assert mapping["H0001-063"]["new_plan_key"] == "H0001-063"


def test_crosswalk_map_terminated_has_no_new_plan_key():
    rows = [_row("H0001", "001", "TERMINATED", "TERMINATED", "terminated")]
    mapping = predict.crosswalk_map_from_rows(rows)
    assert mapping["H0001-001"] == {"disposition": "terminated", "new_plan_key": None}


def test_crosswalk_map_terminated_marker_without_matching_disposition_string():
    """Defense-in-depth: a TERMINATED marker is honored even if disposition
    were ever spelled differently."""
    rows = [_row("H0001", "001", "TERMINATED", "TERMINATED", "some_future_disposition")]
    mapping = predict.crosswalk_map_from_rows(rows)
    assert mapping["H0001-001"]["new_plan_key"] is None


# --- map_prior_year1_to_year2 --------------------------------------------------


def test_map_prior_outside_moves_to_year2_outside_key():
    prior = {OUTSIDE1: 0.4}
    result = predict.map_prior_year1_to_year2(prior, {})
    assert result[OUTSIDE2] == pytest.approx(0.4)


def test_map_prior_renewed_plan_keeps_its_mass_on_successor():
    prior = {"H0001-001": 0.3, OUTSIDE1: 0.7}
    crosswalk_map = predict.crosswalk_map_from_rows([_row("H0001", "001", "H0001", "001", "renewed")])
    result = predict.map_prior_year1_to_year2(prior, crosswalk_map)
    assert result["H0001-001"] == pytest.approx(0.3)
    assert result[OUTSIDE2] == pytest.approx(0.7)
    assert result[predict.NO_SUCCESSOR_BUCKET] == pytest.approx(0.0)


def test_map_prior_consolidated_plans_sum_onto_shared_successor():
    prior = {"H0001-062": 0.1, "H0001-063": 0.15, OUTSIDE1: 0.75}
    crosswalk_map = predict.crosswalk_map_from_rows(
        [
            _row("H0001", "062", "H0001", "063", "consolidated"),
            _row("H0001", "063", "H0001", "063", "consolidated"),
        ]
    )
    result = predict.map_prior_year1_to_year2(prior, crosswalk_map)
    assert result["H0001-063"] == pytest.approx(0.25)


def test_map_prior_terminated_plan_mass_goes_to_no_successor_bucket_not_outside_not_another_plan():
    prior = {"H0001-001": 0.2, "H0002-001": 0.1, OUTSIDE1: 0.7}
    crosswalk_map = predict.crosswalk_map_from_rows(
        [
            _row("H0001", "001", "TERMINATED", "TERMINATED", "terminated"),
            _row("H0002", "001", "H0002", "001", "renewed"),
        ]
    )
    result = predict.map_prior_year1_to_year2(prior, crosswalk_map)
    assert result[predict.NO_SUCCESSOR_BUCKET] == pytest.approx(0.2)
    assert result[OUTSIDE2] == pytest.approx(0.7)  # unchanged: terminated mass did NOT bleed into outside
    assert result["H0002-001"] == pytest.approx(0.1)  # unchanged: did NOT bleed into the surviving plan either
    assert sum(v for k, v in result.items() if k != predict.NO_SUCCESSOR_BUCKET) == pytest.approx(0.8)


def test_map_prior_unknown_key_treated_same_as_terminated():
    prior = {"H9999-999": 0.05, OUTSIDE1: 0.95}
    result = predict.map_prior_year1_to_year2(prior, {})
    assert result[predict.NO_SUCCESSOR_BUCKET] == pytest.approx(0.05)


def test_map_prior_then_renormalize_drops_no_successor_bucket_and_renormalizes_remainder():
    """End-to-end with choice_sets.renormalize_prior_plan: terminated mass is
    excluded entirely (not concentrated onto any one plan) -- the eligible
    remainder renormalizes proportionally, same as any other excluded key."""
    prior = {"A": 0.2, "T": 0.3, OUTSIDE1: 0.5}
    crosswalk_map = predict.crosswalk_map_from_rows(
        [
            _row("H0001", "A", "H0001", "A", "renewed"),
            _row("H0001", "T", "TERMINATED", "TERMINATED", "terminated"),
        ]
    )
    # rewrite prior with real crosswalk-style keys
    prior = {"H0001-A": 0.2, "H0001-T": 0.3, OUTSIDE1: 0.5}
    year2_prior = predict.map_prior_year1_to_year2(prior, crosswalk_map)

    plans_2025 = [{"plan_key": "H0001-A", "snp_type": "Not Applicable"}]
    archetype = {"dual_proxy": False, "age_band": "70-74", "attitude_segment": "mixed"}
    renormalized = choice_sets.renormalize_prior_plan(year2_prior, archetype, plans_2025, OUTSIDE2)

    assert predict.NO_SUCCESSOR_BUCKET not in renormalized or renormalized[predict.NO_SUCCESSOR_BUCKET] == 0.0
    assert sum(renormalized.values()) == pytest.approx(1.0)
    # A:outside were 0.2:0.5 -> renormalized over 0.7, same ratio preserved
    assert renormalized["H0001-A"] == pytest.approx(0.2 / 0.7)
    assert renormalized[OUTSIDE2] == pytest.approx(0.5 / 0.7)


# --- predict_for_archetype / predict_all (synthetic) ---------------------------


def _full_plan(key, snp_type="Not Applicable", **overrides):
    base = {
        "plan_key": key,
        "snp_type": snp_type,
        "premium_total": 20.0,
        "moop_inn": 5000.0,
        "has_comprehensive_dental": True,
        "has_vision": True,
        "has_hearing_aids": False,
        "has_otc_or_flex": True,
        "star_rating": 4.0,
        "is_ppo": False,
        "enrollment_2025_03": 100.0,
    }
    base.update(overrides)
    return base


BASE_COEFFICIENTS = {
    "b_premium": -0.2,
    "b_moop": -0.15,
    "b_dental": 0.3,
    "b_vision_hearing": 0.25,
    "b_otc": 0.2,
    "b_star": 0.4,
    "b_ppo": 0.1,
    "b_inertia": 4.0,
    "b_outside": -1.0,
}


def _archetype(id_, weight, prior, dual_proxy=False, age_band="70-74", attitude_segment="mixed"):
    return {
        "id": id_,
        "weight": weight,
        "dual_proxy": dual_proxy,
        "age_band": age_band,
        "attitude_segment": attitude_segment,
        "prior_plan_year1": prior,
    }


def test_predict_for_archetype_returns_valid_distribution():
    plans = [_full_plan("H0001-A"), _full_plan("H0001-B")]
    crosswalk_map = predict.crosswalk_map_from_rows(
        [_row("H0001", "A", "H0001", "A", "renewed"), _row("H0001", "B", "H0001", "B", "renewed")]
    )
    arche = _archetype("a1", 100.0, {"H0001-A": 0.6, "H0001-B": 0.1, OUTSIDE1: 0.3})

    result = predict.predict_for_archetype(arche, plans, BASE_COEFFICIENTS, crosswalk_map)

    assert set(result["probs"].keys()) == {"H0001-A", "H0001-B", OUTSIDE2}
    assert sum(result["probs"].values()) == pytest.approx(1.0)
    assert result["eligible_plan_keys"] == ["H0001-A", "H0001-B"]
    assert result["renormalized_prior"]["H0001-A"] == pytest.approx(0.6)


def test_predict_for_archetype_respects_dsnp_eligibility():
    plans = [_full_plan("DSNP", snp_type="Dual-Eligible"), _full_plan("OTHER")]
    crosswalk_map = {}
    non_dual = _archetype("a1", 100.0, {}, dual_proxy=False)

    result = predict.predict_for_archetype(non_dual, plans, BASE_COEFFICIENTS, crosswalk_map)

    assert "DSNP" not in result["probs"]
    assert "DSNP" not in result["eligible_plan_keys"]


def test_predict_all_aggregate_shares_sum_to_one_and_are_weight_averaged():
    plans = [_full_plan("A"), _full_plan("B")]
    crosswalk_map = predict.crosswalk_map_from_rows(
        [_row("H0001", "A", "H0001", "A", "renewed"), _row("H0001", "B", "H0001", "B", "renewed")]
    )
    archetypes = [
        _archetype("a1", 100.0, {"H0001-A": 1.0}),
        _archetype("a2", 300.0, {"H0001-B": 1.0}),
    ]

    result = predict.predict_all(archetypes, plans, BASE_COEFFICIENTS, crosswalk_map)

    assert set(result["per_archetype"].keys()) == {"a1", "a2"}
    assert sum(result["aggregate_shares"].values()) == pytest.approx(1.0)
    # a2 (weight 300) dominates the population 3:1 over a1 (weight 100)
    manual = {}
    total_w = 400.0
    for aid, w in (("a1", 100.0), ("a2", 300.0)):
        for key, prob in result["per_archetype"][aid]["probs"].items():
            manual[key] = manual.get(key, 0.0) + w * prob / total_w
    assert result["aggregate_shares"] == pytest.approx(manual)


def test_terminated_mass_by_archetype_diagnostic():
    crosswalk_map = predict.crosswalk_map_from_rows([_row("H0001", "A", "TERMINATED", "TERMINATED", "terminated")])
    archetypes = [_archetype("a1", 100.0, {"H0001-A": 0.25, OUTSIDE1: 0.75})]
    result = predict.terminated_mass_by_archetype(archetypes, crosswalk_map)
    assert result["a1"] == pytest.approx(0.25)


# --- real-data integration ------------------------------------------------------


def _real_data_available() -> bool:
    return (
        (settings.PROCESSED_DIR / "archetypes.json").exists()
        and (settings.PROCESSED_DIR / "plans_2025.json").exists()
        and (settings.PROCESSED_DIR / "coefficients.json").exists()
        and (settings.INTERIM_DIR / "plan_crosswalk_2024_2025.parquet").exists()
    )


def _load_real():
    archetypes = json.loads((settings.PROCESSED_DIR / "archetypes.json").read_text())["archetypes"]
    plans_2025 = json.loads((settings.PROCESSED_DIR / "plans_2025.json").read_text())["plans"]
    coefficients = json.loads((settings.PROCESSED_DIR / "coefficients.json").read_text())
    crosswalk_map = predict.load_crosswalk_map()
    return archetypes, plans_2025, coefficients, crosswalk_map


@pytest.mark.integration
def test_real_predict_all_produces_valid_distributions_for_every_archetype():
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    archetypes, plans_2025, coefficients, crosswalk_map = _load_real()

    result = predict.predict_all(archetypes, plans_2025, coefficients["base_coefficients"], crosswalk_map)

    assert len(result["per_archetype"]) == len(archetypes) == 80
    for aid, per in result["per_archetype"].items():
        assert sum(per["probs"].values()) == pytest.approx(1.0, abs=1e-9)
        assert all(p >= 0.0 for p in per["probs"].values())
    assert sum(result["aggregate_shares"].values()) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.integration
def test_real_predict_all_is_deterministic():
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    archetypes, plans_2025, coefficients, crosswalk_map = _load_real()

    result_a = predict.predict_all(archetypes, plans_2025, coefficients["base_coefficients"], crosswalk_map)
    result_b = predict.predict_all(archetypes, plans_2025, coefficients["base_coefficients"], crosswalk_map)

    assert result_a == result_b


@pytest.mark.integration
def test_real_terminated_plans_hold_no_inertia_for_any_surviving_plan():
    """Direct real-data check of the spec requirement: no archetype's
    crosswalk-mapped Year-2 prior carries the *raw* (pre-renormalization)
    terminated-plan mass onto some other specific plan or the outside
    option -- it only ever appears under NO_SUCCESSOR_BUCKET."""
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    archetypes, plans_2025, coefficients, crosswalk_map = _load_real()

    terminated_2024_keys = {old for old, entry in crosswalk_map.items() if entry["new_plan_key"] is None}
    assert len(terminated_2024_keys) == 9  # per spec: 9 terminated dispositions

    for archetype in archetypes:
        prior = archetype["prior_plan_year1"]
        raw_terminated_mass = sum(prior.get(key, 0.0) for key in terminated_2024_keys)
        year2_prior = predict.map_prior_year1_to_year2(prior, crosswalk_map)
        assert year2_prior[predict.NO_SUCCESSOR_BUCKET] == pytest.approx(raw_terminated_mass)


@pytest.mark.integration
def test_real_crosswalk_disposition_counts_match_spec():
    if not _real_data_available():
        pytest.skip("processed/interim real data not present")
    _, _, _, crosswalk_map = _load_real()
    dispositions = [entry["disposition"] for entry in crosswalk_map.values()]
    assert len(dispositions) == 93
    counts = {d: dispositions.count(d) for d in set(dispositions)}
    assert counts.get("renewed") == 74
    assert counts.get("terminated") == 9
    assert counts.get("consolidated") == 7
    assert counts.get("renumbered") == 3
