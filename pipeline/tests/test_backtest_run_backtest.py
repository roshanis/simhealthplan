"""Tests for backtest/run_backtest.py — the Phase 5 orchestrator.

Small synthetic-fixture tests exercise the trickiest wiring decisions (new
2025 plans get share_2024=0, terminated-plan redistribution differs between
the ground-truth share_2024 basis and the naive-baseline predictions,
beats_naive is null for an uncomputed blended variant, schema validation)
without touching real data or the network. The real-data integration tests
are the master acceptance suite for the Phase 5 spec: schema validation,
deterministic byte-identical reruns, bounds containing the point estimate,
every variant's shares summing to 1, and both baselines being computed (or
trend's absence being structurally documented).
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest import bounds as bounds_module
from backtest import run_backtest
from backtest.schemas import BacktestResult
from choice_model import predict
from config.settings import settings

OUTSIDE1 = predict.OUTSIDE_KEY_YEAR1
OUTSIDE2 = predict.OUTSIDE_KEY_YEAR2


# --- synthetic fixtures --------------------------------------------------------------


def _plan_2024(key, contract_id, plan_id, **overrides):
    base = {
        "plan_key": key,
        "contract_id": contract_id,
        "plan_id": plan_id,
        "org_name": "Test Org",
        "plan_name": f"Plan {key}",
        "snp_type": "Not Applicable",
        "premium_total": 20.0,
        "moop_inn": 5000.0,
        "has_comprehensive_dental": True,
        "has_vision": True,
        "has_hearing_aids": False,
        "has_otc_or_flex": True,
        "star_rating": 4.0,
        "is_ppo": False,
        "enrollment_2024_03": 100.0,
    }
    base.update(overrides)
    return base


def _plan_2025(key, contract_id, plan_id, **overrides):
    base = {
        "plan_key": key,
        "contract_id": contract_id,
        "plan_id": plan_id,
        "org_name": "Test Org",
        "plan_name": f"Plan {key}",
        "snp_type": "Not Applicable",
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


def _archetype(id_, weight, prior, dual_proxy=False, age_band="70-74", attitude_segment="mixed"):
    return {
        "id": id_,
        "weight": weight,
        "dual_proxy": dual_proxy,
        "age_band": age_band,
        "attitude_segment": attitude_segment,
        "prior_plan_year1": prior,
    }


def _row(old_c, old_p, new_c, new_p, disposition):
    return {
        "old_contract_id": old_c,
        "old_plan_id": old_p,
        "new_contract_id": new_c,
        "new_plan_id": new_p,
        "disposition": disposition,
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


def _cpsc_df(rows: list[tuple[str, str, object, bool]], year_month: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "contract_id": [r[0] for r in rows],
            "plan_id": [r[1] for r in rows],
            "fips": ["04013"] * len(rows),
            "enrollment": pd.array([r[2] for r in rows], dtype="Int64"),
            "suppressed": [r[3] for r in rows],
            "year_month": [year_month] * len(rows),
        }
    )


def _penetration_df(eligibles: int, year_month: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "state": ["Arizona"],
            "county": ["Maricopa"],
            "fips": ["04013"],
            "ssa": ["03060"],
            "eligibles": pd.array([eligibles], dtype="Int64"),
            "enrolled": pd.array([eligibles // 2], dtype="Int64"),
            "penetration": [0.5],
            "year_month": [year_month],
        }
    )


def _small_inputs() -> dict:
    # 2024 universe: H0001-A (renewed -> H0001-A), H0001-B (terminated)
    # 2025 universe: H0001-A (renewed), H0001-C (brand new, no 2024 predecessor)
    plans_2024 = [_plan_2024("H0001-A", "H0001", "A"), _plan_2024("H0001-B", "H0001", "B")]
    plans_2025 = [_plan_2025("H0001-A", "H0001", "A"), _plan_2025("H0001-C", "H0001", "C")]
    crosswalk_map = predict.crosswalk_map_from_rows(
        [
            _row("H0001", "A", "H0001", "A", "renewed"),
            _row("H0001", "B", "TERMINATED", "TERMINATED", "terminated"),
        ]
    )
    archetypes = [
        _archetype("a1", 400.0, {"H0001-A": 0.5, "H0001-B": 0.2, OUTSIDE1: 0.3}),
        _archetype("a2", 600.0, {"H0001-A": 0.1, OUTSIDE1: 0.9}),
    ]
    coefficients = {"base_coefficients": BASE_COEFFICIENTS}

    cpsc_2024_df = _cpsc_df([("H0001", "A", 200, False), ("H0001", "B", 100, False)], "2024-03")
    cpsc_2025_df = _cpsc_df([("H0001", "A", 250, False), ("H0001", "C", 50, False)], "2025-03")
    penetration_2024_df = _penetration_df(1000, "2024-03")
    penetration_2025_df = _penetration_df(1000, "2025-03")

    return dict(
        archetypes=archetypes,
        plans_2024=plans_2024,
        plans_2025=plans_2025,
        coefficients=coefficients,
        crosswalk_map=crosswalk_map,
        cpsc_2024_df=cpsc_2024_df,
        cpsc_2025_df=cpsc_2025_df,
        penetration_2024_df=penetration_2024_df,
        penetration_2025_df=penetration_2025_df,
        n_bounds_draws=20,
        seed=1,
        attempt_trend=False,
    )


# --- synthetic wiring tests -----------------------------------------------------------


def test_run_backtest_row_keys_are_2025_plans_plus_outside():
    result = run_backtest.run_backtest(**_small_inputs())
    keys = {row["plan_key"] for row in result["per_plan"]}
    assert keys == {"H0001-A", "H0001-C", OUTSIDE2}


def test_run_backtest_new_2025_plan_has_zero_2024_baseline():
    result = run_backtest.run_backtest(**_small_inputs())
    row_c = next(r for r in result["per_plan"] if r["plan_key"] == "H0001-C")
    assert row_c["enrollment_2024"] == 0.0
    assert row_c["share_2024"] == 0.0
    # shift_actual for a brand-new plan is just its full actual 2025 share
    assert row_c["shift_actual"] == pytest.approx(row_c["share_2025_actual"])


def test_run_backtest_blended_and_trend_fields_are_null_when_unavailable():
    result = run_backtest.run_backtest(**_small_inputs())
    for row in result["per_plan"]:
        assert row["share_2025_pred_blended"] is None
        assert row["shift_pred_blended"] is None
        assert row["abs_error_blended"] is None
        assert row["share_2025_naive_trend"] is None
        assert row["shift_naive_trend"] is None
        assert row["abs_error_naive_trend"] is None
    assert result["summary"]["weighted_mae"]["blended"] is None
    assert result["summary"]["weighted_mae"]["trend"] is None
    assert result["summary"]["beats_naive"]["blended"] is None
    assert result["metadata"]["trend_baseline"]["attempted"] is False


def test_run_backtest_best_naive_is_no_change_when_trend_unavailable():
    result = run_backtest.run_backtest(**_small_inputs())
    assert result["summary"]["best_naive"]["selected"] == "no_change"


def test_run_backtest_no_change_baseline_sums_to_one_but_ground_truth_share_2024_does_not():
    result = run_backtest.run_backtest(**_small_inputs())
    total_no_change = sum(r["share_2025_naive_nochange"] for r in result["per_plan"])
    total_share_2024 = sum(r["share_2024"] for r in result["per_plan"])
    assert total_no_change == pytest.approx(1.0)
    # H0001-B terminated with 2024 share 100/1000=0.10 -> dropped, not
    # redistributed, from the ground-truth share_2024 basis (documented).
    assert total_share_2024 == pytest.approx(1.0 - 0.10, abs=1e-9)


def test_run_backtest_actual_and_logit_shares_sum_to_one():
    result = run_backtest.run_backtest(**_small_inputs())
    total_actual = sum(r["share_2025_actual"] for r in result["per_plan"])
    total_logit = sum(r["share_2025_pred_logit"] for r in result["per_plan"])
    assert total_actual == pytest.approx(1.0)
    assert total_logit == pytest.approx(1.0)


def test_run_backtest_beats_naive_logit_is_explicit_boolean():
    result = run_backtest.run_backtest(**_small_inputs())
    assert isinstance(result["summary"]["beats_naive"]["logit"], bool)


def test_run_backtest_bounds_present_for_logit_variant_keys():
    result = run_backtest.run_backtest(**_small_inputs())
    assert set(result["bounds"].keys()) == {"H0001-A", "H0001-C", OUTSIDE2}
    for row in result["bounds"].values():
        assert row["p10"] <= row["p50"] <= row["p90"]
    assert result["metadata"]["primary_bounds_variant"] == "logit"


def test_run_backtest_validates_against_schema():
    result = run_backtest.run_backtest(**_small_inputs())
    BacktestResult.model_validate(result)  # raises on schema mismatch


def test_run_backtest_deterministic_given_fixed_seed():
    inputs = _small_inputs()
    result_a = run_backtest.run_backtest(**inputs)
    result_b = run_backtest.run_backtest(**inputs)
    assert result_a == result_b


# --- real-data integration -----------------------------------------------------------


def _real_data_available() -> bool:
    return (
        (settings.PROCESSED_DIR / "archetypes.json").exists()
        and (settings.PROCESSED_DIR / "plans_2024.json").exists()
        and (settings.PROCESSED_DIR / "plans_2025.json").exists()
        and (settings.PROCESSED_DIR / "coefficients.json").exists()
        and (settings.INTERIM_DIR / "plan_crosswalk_2024_2025.parquet").exists()
        and (settings.INTERIM_DIR / "cpsc_2024_03.parquet").exists()
        and (settings.INTERIM_DIR / "cpsc_2025_03.parquet").exists()
        and (settings.INTERIM_DIR / "penetration_2024_03.parquet").exists()
        and (settings.INTERIM_DIR / "penetration_2025_03.parquet").exists()
    )


@pytest.mark.integration
def test_real_run_backtest_validates_against_schema():
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    inputs = run_backtest._load_real_inputs()
    result = run_backtest.run_backtest(**inputs, n_bounds_draws=60, attempt_trend=True)
    BacktestResult.model_validate(result)


@pytest.mark.integration
def test_real_run_backtest_every_variant_sums_to_one():
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    inputs = run_backtest._load_real_inputs()
    result = run_backtest.run_backtest(**inputs, n_bounds_draws=60, attempt_trend=True)

    total_actual = sum(r["share_2025_actual"] for r in result["per_plan"])
    total_logit = sum(r["share_2025_pred_logit"] for r in result["per_plan"])
    total_nochange = sum(r["share_2025_naive_nochange"] for r in result["per_plan"])
    assert total_actual == pytest.approx(1.0, abs=1e-9)
    assert total_logit == pytest.approx(1.0, abs=1e-9)
    assert total_nochange == pytest.approx(1.0, abs=1e-9)

    if result["metadata"]["trend_baseline"].get("available"):
        total_trend = sum(r["share_2025_naive_trend"] for r in result["per_plan"])
        assert total_trend == pytest.approx(1.0, abs=1e-9)

    if result["metadata"]["model_variants_included"] == ["logit", "blended"]:
        total_blended = sum(r["share_2025_pred_blended"] for r in result["per_plan"])
        assert total_blended == pytest.approx(1.0, abs=1e-9)


@pytest.mark.integration
def test_real_run_backtest_bounds_contain_point_estimate():
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    inputs = run_backtest._load_real_inputs()
    result = run_backtest.run_backtest(**inputs, n_bounds_draws=200, attempt_trend=False)

    primary_variant = result["metadata"]["primary_bounds_variant"]
    point_field = {"logit": "share_2025_pred_logit", "blended": "share_2025_pred_blended"}[primary_variant]

    violations = []
    for row in result["per_plan"]:
        point = row[point_field]
        band = result["bounds"][row["plan_key"]]
        if not (band["p10"] <= point <= band["p90"]):
            violations.append((row["plan_key"], point, band))
    assert violations == [], f"{len(violations)} plans had point estimate outside [p10, p90]: {violations[:5]}"

    # outside option too
    outside_point = next(r for r in result["per_plan"] if r["plan_key"] == OUTSIDE2)[point_field]
    outside_band = result["bounds"][OUTSIDE2]
    assert outside_band["p10"] <= outside_point <= outside_band["p90"]


@pytest.mark.integration
def test_real_both_baselines_computed_or_trend_structurally_documented():
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    inputs = run_backtest._load_real_inputs()
    result = run_backtest.run_backtest(**inputs, n_bounds_draws=20, attempt_trend=True)

    # no_change is always computable
    assert result["summary"]["weighted_mae"]["no_change"] is not None
    trend_meta = result["metadata"]["trend_baseline"]
    assert trend_meta["attempted"] is True
    if trend_meta["available"]:
        assert result["summary"]["weighted_mae"]["trend"] is not None
    else:
        assert result["summary"]["weighted_mae"]["trend"] is None
        assert "unavailable_reason" in trend_meta


@pytest.mark.integration
def test_real_beats_naive_computed_by_explicit_rule_not_hand_set():
    """Independently recomputes beats_naive['logit'] from the summary's own
    weighted_mae/directional_accuracy + best_naive selection and checks it
    matches exactly -- guards against the field ever being hand-set."""
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    from backtest import metrics

    inputs = run_backtest._load_real_inputs()
    result = run_backtest.run_backtest(**inputs, n_bounds_draws=20, attempt_trend=True)
    summary = result["summary"]

    best_naive_name = summary["best_naive"]["selected"]
    expected = metrics.beats_naive(
        summary["weighted_mae"]["logit"],
        summary["directional_accuracy"]["logit"],
        summary["weighted_mae"][best_naive_name],
        summary["directional_accuracy"][best_naive_name],
    )
    assert summary["beats_naive"]["logit"] == expected


@pytest.mark.integration
def test_real_deterministic_build_is_byte_identical(tmp_path):
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    run_backtest.build(output_dir=dir_a, n_bounds_draws=60)
    run_backtest.build(output_dir=dir_b, n_bounds_draws=60)
    bytes_a = (dir_a / run_backtest.RESULT_FILENAME).read_bytes()
    bytes_b = (dir_b / run_backtest.RESULT_FILENAME).read_bytes()
    assert bytes_a == bytes_b


@pytest.mark.integration
def test_real_output_file_written_and_schema_valid():
    """This is the live `make backtest` run: writes the real, committed
    data/processed/backtest_result.json using the full N=1000-draw bounds
    spec default, exactly like `python -m backtest.run_backtest` does."""
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    run_backtest.build()
    path = settings.PROCESSED_DIR / run_backtest.RESULT_FILENAME
    assert path.exists()
    on_disk = json.loads(path.read_text())
    BacktestResult.model_validate(on_disk)
    assert on_disk["metadata"]["n_bounds_draws"] == bounds_module.N_DRAWS_DEFAULT
