"""Tests for choice_model/choice_sets.py — Phase 3 eligibility rules.

TDD against small synthetic archetype/plan dicts. The real-data
renormalization-fidelity test (post-renormalization aggregate shares still
reproduce actual 2024 within 1pp size-weighted MAE) is an integration test
against archetypes.json + plans_2024.json.
"""

from __future__ import annotations

import json

import pytest

from choice_model import choice_sets, utility
from config.settings import settings

OUTSIDE_KEY = "other_or_no_ma_2024"


def _plan(key, snp_type="Not Applicable"):
    return {"plan_key": key, "snp_type": snp_type}


def _archetype(dual_proxy=False, age_band="70-74", attitude_segment="mixed"):
    return {"dual_proxy": dual_proxy, "age_band": age_band, "attitude_segment": attitude_segment}


# --- is_eligible ------------------------------------------------------------


def test_dsnp_plan_eligible_only_for_dual_proxy():
    dsnp = _plan("D1", snp_type="Dual-Eligible")
    assert choice_sets.is_eligible(_archetype(dual_proxy=True), dsnp) is True
    assert choice_sets.is_eligible(_archetype(dual_proxy=False), dsnp) is False


def test_isnp_plan_eligible_only_for_85_plus():
    isnp = _plan("I1", snp_type="Institutional")
    assert choice_sets.is_eligible(_archetype(age_band="85+"), isnp) is True
    assert choice_sets.is_eligible(_archetype(age_band="75-84"), isnp) is False
    assert choice_sets.is_eligible(_archetype(age_band="65-69"), isnp) is False


def test_csnp_plan_eligible_only_for_health_status_driven():
    csnp = _plan("C1", snp_type="Chronic or Disabling Condition")
    assert choice_sets.is_eligible(_archetype(attitude_segment="health_status_driven"), csnp) is True
    assert choice_sets.is_eligible(_archetype(attitude_segment="price_sensitive"), csnp) is False
    assert choice_sets.is_eligible(_archetype(attitude_segment="mixed"), csnp) is False


def test_non_snp_plan_eligible_for_everyone():
    plan = _plan("P1", snp_type="Not Applicable")
    assert choice_sets.is_eligible(_archetype(), plan) is True
    assert choice_sets.is_eligible(_archetype(dual_proxy=True, age_band="85+", attitude_segment="health_status_driven"), plan) is True


def test_dual_85_plus_health_status_driven_archetype_eligible_for_all_snp_types():
    arche = _archetype(dual_proxy=True, age_band="85+", attitude_segment="health_status_driven")
    for snp in ("Not Applicable", "Dual-Eligible", "Institutional", "Chronic or Disabling Condition"):
        assert choice_sets.is_eligible(arche, _plan("X", snp_type=snp)) is True


# --- eligible_plan_keys -------------------------------------------------------


def test_eligible_plan_keys_filters_correctly():
    plans = [
        _plan("A", "Not Applicable"),
        _plan("B", "Dual-Eligible"),
        _plan("C", "Institutional"),
        _plan("D", "Chronic or Disabling Condition"),
    ]
    arche = _archetype(dual_proxy=False, age_band="70-74", attitude_segment="mixed")
    assert choice_sets.eligible_plan_keys(arche, plans) == ["A"]


def _full_plan(key, snp_type="Not Applicable"):
    """A plan dict with every attribute utility.choice_probabilities needs."""
    return {
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
    }


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


@pytest.mark.parametrize(
    "snp_type,archetype_kwargs",
    [
        ("Dual-Eligible", {"dual_proxy": False}),
        ("Institutional", {"age_band": "70-74"}),
        ("Chronic or Disabling Condition", {"attitude_segment": "price_sensitive"}),
    ],
)
def test_excluded_snp_plan_gets_exactly_zero_probability_end_to_end(snp_type, archetype_kwargs):
    """choice_sets.eligible_plans + utility.choice_probabilities together: an
    archetype ineligible for a D-SNP/I-SNP/C-SNP plan gets exactly zero
    probability mass on it (the plan simply isn't a member of the softmax's
    choice set, so it can hold no probability at all)."""
    excluded = _full_plan("EXCLUDED", snp_type=snp_type)
    other = _full_plan("OTHER", snp_type="Not Applicable")
    plans = [excluded, other]
    arche = _archetype(**archetype_kwargs)

    eligible = choice_sets.eligible_plans(arche, plans)
    assert "EXCLUDED" not in {p["plan_key"] for p in eligible}

    prior = {"EXCLUDED": 0.5, "OTHER": 0.3, OUTSIDE_KEY: 0.2}
    renormalized = choice_sets.renormalize_prior_plan(prior, arche, plans, OUTSIDE_KEY)
    probs = utility.choice_probabilities(BASE_COEFFICIENTS, arche["attitude_segment"], eligible, renormalized, OUTSIDE_KEY)

    assert "EXCLUDED" not in probs
    assert probs.get("EXCLUDED", 0.0) == 0.0
    assert sum(probs.values()) == pytest.approx(1.0)


# --- renormalize_prior_plan ----------------------------------------------------


def test_renormalize_prior_plan_zeroes_ineligible_and_renormalizes():
    plans = [
        _plan("A", "Not Applicable"),
        _plan("B", "Institutional"),  # ineligible for this archetype
    ]
    arche = _archetype(dual_proxy=False, age_band="70-74", attitude_segment="mixed")
    prior = {"A": 0.5, "B": 0.3, OUTSIDE_KEY: 0.2}

    result = choice_sets.renormalize_prior_plan(prior, arche, plans, OUTSIDE_KEY)

    assert result["B"] == 0.0
    assert sum(result.values()) == pytest.approx(1.0)
    # A and OUTSIDE keep their relative proportion: 0.5:0.2 -> renormalized over 0.7
    assert result["A"] == pytest.approx(0.5 / 0.7)
    assert result[OUTSIDE_KEY] == pytest.approx(0.2 / 0.7)


def test_renormalize_prior_plan_no_change_when_all_eligible():
    plans = [_plan("A"), _plan("B")]
    arche = _archetype()
    prior = {"A": 0.4, "B": 0.3, OUTSIDE_KEY: 0.3}
    result = choice_sets.renormalize_prior_plan(prior, arche, plans, OUTSIDE_KEY)
    assert result == pytest.approx(prior)


def test_renormalize_prior_plan_degenerate_all_mass_on_ineligible_falls_back_to_outside():
    plans = [_plan("A", "Institutional")]
    arche = _archetype(age_band="70-74")  # not 85+, A is ineligible
    prior = {"A": 1.0, OUTSIDE_KEY: 0.0}
    result = choice_sets.renormalize_prior_plan(prior, arche, plans, OUTSIDE_KEY)
    assert result[OUTSIDE_KEY] == pytest.approx(1.0)
    assert result["A"] == 0.0


def test_renormalize_prior_plan_outside_always_eligible():
    plans = [_plan("A", "Dual-Eligible")]
    arche = _archetype(dual_proxy=False)
    prior = {"A": 0.9, OUTSIDE_KEY: 0.1}
    result = choice_sets.renormalize_prior_plan(prior, arche, plans, OUTSIDE_KEY)
    assert result[OUTSIDE_KEY] == pytest.approx(1.0)
    assert result["A"] == 0.0


# --- module documents proxies (docstring / metadata) ----------------------------


def test_module_docstring_documents_isnp_and_csnp_as_proxies():
    doc = choice_sets.__doc__ or ""
    assert "proxy" in doc.lower() or "proxies" in doc.lower()
    assert "institutional" in doc.lower() or "i-snp" in doc.lower()
    assert "chronic" in doc.lower() or "c-snp" in doc.lower()


def test_rules_metadata_documents_proxy_flags():
    rules = choice_sets.CHOICE_SET_RULES
    assert rules["dsnp"]["proxy"] is False
    assert rules["isnp"]["proxy"] is True
    assert rules["csnp"]["proxy"] is True


# --- integration: real data ------------------------------------------------------


def _real_data_available() -> bool:
    return (settings.PROCESSED_DIR / "archetypes.json").exists() and (settings.PROCESSED_DIR / "plans_2024.json").exists()


@pytest.mark.integration
def test_real_renormalized_shares_still_reproduce_actual_2024_within_1pp():
    if not _real_data_available():
        pytest.skip("processed archetypes.json / plans_2024.json not present; run `make archetypes calibrate` first")

    archetypes = json.loads((settings.PROCESSED_DIR / "archetypes.json").read_text())["archetypes"]
    plans_result = json.loads((settings.PROCESSED_DIR / "plans_2024.json").read_text())
    plans = plans_result["plans"]

    weight_by_id = {a["id"]: a["weight"] for a in archetypes}
    recon: dict[str, float] = {}
    for a in archetypes:
        renorm = choice_sets.renormalize_prior_plan(a["prior_plan_year1"], a, plans, OUTSIDE_KEY)
        w = weight_by_id[a["id"]]
        for key, prob in renorm.items():
            recon[key] = recon.get(key, 0.0) + w * prob

    actual = {p["plan_key"]: p["enrollment_2024_03"] for p in plans}
    landscape_total = sum(actual.values())
    eligibles_total = sum(weight_by_id.values())
    actual[OUTSIDE_KEY] = eligibles_total - landscape_total

    errs = []
    weights = []
    for key, actual_count in actual.items():
        actual_share = actual_count / eligibles_total
        recon_share = recon.get(key, 0.0) / eligibles_total
        errs.append(abs(actual_share - recon_share))
        weights.append(actual_count)

    total_weight = sum(weights)
    size_weighted_mae_pp = sum(e * w for e, w in zip(errs, weights)) / total_weight * 100
    assert size_weighted_mae_pp < 1.0
