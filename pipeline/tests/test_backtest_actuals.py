"""Tests for backtest/actuals.py — actual enrollment shares from CPSC + penetration.

Unit tests exercise the pure/DataFrame-level helpers against small synthetic
fixtures (mirroring the real cpsc_*.parquet / penetration_*.parquet column
shapes -- see parse/cpsc.py::EXPECTED_COLUMNS and parse/penetration.py::
EXPECTED_COLUMNS). Real-data integration tests validate against the
committed 2024/2025 interim parquet files.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest import actuals
from config.settings import settings

OUTSIDE = "outside_test"


def _cpsc_df(rows: list[tuple[str, str, object, bool]]) -> pd.DataFrame:
    """rows: (contract_id, plan_id, enrollment, suppressed)."""
    return pd.DataFrame(
        {
            "contract_id": [r[0] for r in rows],
            "plan_id": [r[1] for r in rows],
            "fips": ["04013"] * len(rows),
            "enrollment": pd.array([r[2] for r in rows], dtype="Int64"),
            "suppressed": [r[3] for r in rows],
            "year_month": ["2025-03"] * len(rows),
        }
    )


def _penetration_df(eligibles: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "state": ["Arizona"],
            "county": ["Maricopa"],
            "fips": ["04013"],
            "ssa": ["03060"],
            "eligibles": pd.array([eligibles], dtype="Int64"),
            "enrolled": pd.array([eligibles // 2], dtype="Int64"),
            "penetration": [0.5],
            "year_month": ["2025-03"],
        }
    )


# --- enrollment_by_plan -----------------------------------------------------------


def test_enrollment_by_plan_sums_known_values():
    df = _cpsc_df([("H0001", "001", 100, False), ("H0001", "002", 50, False)])
    result = actuals.enrollment_by_plan(df, ["H0001-001", "H0001-002"])
    assert result == {"H0001-001": 100.0, "H0001-002": 50.0}


def test_enrollment_by_plan_suppressed_imputed_to_5():
    df = _cpsc_df([("H0001", "001", None, True)])
    result = actuals.enrollment_by_plan(df, ["H0001-001"])
    assert result["H0001-001"] == pytest.approx(5.0)


def test_enrollment_by_plan_missing_plan_key_defaults_to_zero():
    df = _cpsc_df([("H0001", "001", 10, False)])
    result = actuals.enrollment_by_plan(df, ["H0001-001", "H9999-999"])
    assert result["H9999-999"] == 0.0


def test_enrollment_by_plan_drops_rows_outside_universe():
    df = _cpsc_df([("H0001", "001", 10, False), ("H9999", "999", 99999, False)])
    result = actuals.enrollment_by_plan(df, ["H0001-001"])
    assert result == {"H0001-001": 10.0}
    assert "H9999-999" not in result


def test_enrollment_by_plan_sums_multiple_rows_same_plan_key():
    # e.g. two SSA-county rows for the same plan both mapping to the county fips
    df = _cpsc_df([("H0001", "001", 10, False), ("H0001", "001", 5, False)])
    result = actuals.enrollment_by_plan(df, ["H0001-001"])
    assert result["H0001-001"] == pytest.approx(15.0)


# --- eligibles_total ---------------------------------------------------------------


def test_eligibles_total_reads_single_row():
    df = _penetration_df(1000)
    assert actuals.eligibles_total(df) == pytest.approx(1000.0)


# --- actual_shares / actual_counts --------------------------------------------------


def test_actual_shares_sum_to_one_including_outside():
    cpsc = _cpsc_df([("H0001", "001", 100, False), ("H0001", "002", 50, False)])
    penetration = _penetration_df(1000)
    result = actuals.actual_shares(cpsc, penetration, ["H0001-001", "H0001-002"], OUTSIDE)
    assert result["H0001-001"] == pytest.approx(0.1)
    assert result["H0001-002"] == pytest.approx(0.05)
    assert result[OUTSIDE] == pytest.approx(0.85)
    assert sum(result.values()) == pytest.approx(1.0)


def test_actual_counts_outside_is_eligibles_minus_modeled_enrollment():
    cpsc = _cpsc_df([("H0001", "001", 100, False)])
    penetration = _penetration_df(1000)
    result = actuals.actual_counts(cpsc, penetration, ["H0001-001"], OUTSIDE)
    assert result["H0001-001"] == pytest.approx(100.0)
    assert result[OUTSIDE] == pytest.approx(900.0)


# --- suppressed_plan_keys -----------------------------------------------------------


def test_suppressed_plan_keys_identifies_suppressed_only():
    df = _cpsc_df([("H0001", "001", None, True), ("H0001", "002", 50, False)])
    result = actuals.suppressed_plan_keys(df, ["H0001-001", "H0001-002"])
    assert result == {"H0001-001"}


def test_suppressed_plan_keys_empty_when_none_suppressed():
    df = _cpsc_df([("H0001", "001", 10, False)])
    result = actuals.suppressed_plan_keys(df, ["H0001-001"])
    assert result == set()


def test_suppressed_plan_keys_ignores_keys_outside_universe():
    df = _cpsc_df([("H9999", "999", None, True)])
    result = actuals.suppressed_plan_keys(df, ["H0001-001"])
    assert result == set()


# --- real-data integration ----------------------------------------------------------


def _real_data_available() -> bool:
    return (
        (settings.INTERIM_DIR / "cpsc_2024_03.parquet").exists()
        and (settings.INTERIM_DIR / "cpsc_2025_03.parquet").exists()
        and (settings.INTERIM_DIR / "penetration_2024_03.parquet").exists()
        and (settings.INTERIM_DIR / "penetration_2025_03.parquet").exists()
        and (settings.PROCESSED_DIR / "plans_2025.json").exists()
    )


@pytest.mark.integration
def test_real_actual_shares_2025_matches_plans_2025_enrollment_field():
    """Cross-checks this module's independent CPSC/penetration read against
    plan_attributes.py's already-committed enrollment_2025_03 column (same
    suppressed->5 convention) -- they should agree exactly per plan."""
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    import json

    plans_2025 = json.loads((settings.PROCESSED_DIR / "plans_2025.json").read_text())["plans"]
    plan_keys = [p["plan_key"] for p in plans_2025]

    cpsc = pd.read_parquet(settings.INTERIM_DIR / "cpsc_2025_03.parquet")
    penetration = pd.read_parquet(settings.INTERIM_DIR / "penetration_2025_03.parquet")
    counts = actuals.enrollment_by_plan(cpsc, plan_keys)

    for plan in plans_2025:
        assert counts[plan["plan_key"]] == pytest.approx(plan["enrollment_2025_03"])


@pytest.mark.integration
def test_real_actual_shares_2025_sum_to_one():
    if not _real_data_available():
        pytest.skip("real interim/processed data not present")
    import json

    plans_2025 = json.loads((settings.PROCESSED_DIR / "plans_2025.json").read_text())["plans"]
    plan_keys = [p["plan_key"] for p in plans_2025]

    cpsc = pd.read_parquet(settings.INTERIM_DIR / "cpsc_2025_03.parquet")
    penetration = pd.read_parquet(settings.INTERIM_DIR / "penetration_2025_03.parquet")
    shares = actuals.actual_shares(cpsc, penetration, plan_keys, "outside_2025")

    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-9)
    assert shares["outside_2025"] > 0.0
