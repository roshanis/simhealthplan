"""Tests for backtest/baselines.py — the two naive backtest baselines.

Unit tests exercise the pure crosswalk-mapping + extrapolation math against
small synthetic fixtures (reusing choice_model/predict.py's crosswalk
helpers, not reimplementing crosswalk traversal). The 2023 CPSC
ingest/parse plumbing (``ensure_cpsc_2023_ingested`` / ``load_or_parse_cpsc_2023``)
is exercised only by the live integration test, since it needs real network
access -- see run_backtest.py's live-run notes for whether that succeeded.
"""

from __future__ import annotations

import httpx
import pandas as pd
import pytest

from backtest import baselines
from choice_model import predict

OUTSIDE1 = predict.OUTSIDE_KEY_YEAR1
OUTSIDE2 = predict.OUTSIDE_KEY_YEAR2


def _row(old_c, old_p, new_c, new_p, disposition):
    return {
        "old_contract_id": old_c,
        "old_plan_id": old_p,
        "new_contract_id": new_c,
        "new_plan_id": new_p,
        "disposition": disposition,
    }


# --- no_change_baseline -----------------------------------------------------------


def test_no_change_baseline_renewed_plan_keeps_its_share():
    share_2024 = {"H0001-A": 0.3, OUTSIDE1: 0.7}
    crosswalk_map = predict.crosswalk_map_from_rows([_row("H0001", "A", "H0001", "A", "renewed")])
    result = baselines.no_change_baseline(share_2024, crosswalk_map)
    assert result["H0001-A"] == pytest.approx(0.3)
    assert result[OUTSIDE2] == pytest.approx(0.7)
    assert sum(result.values()) == pytest.approx(1.0)


def test_no_change_baseline_terminated_plan_share_redistributed_proportionally():
    # H0001-A survives (renewed), H0001-B terminates. B's 0.2 share should
    # spread proportionally across A (0.3) and outside (0.5), i.e. scaled by
    # 1 / (1 - 0.2) = 1.25.
    share_2024 = {"H0001-A": 0.3, "H0001-B": 0.2, OUTSIDE1: 0.5}
    crosswalk_map = predict.crosswalk_map_from_rows(
        [
            _row("H0001", "A", "H0001", "A", "renewed"),
            _row("H0001", "B", "TERMINATED", "TERMINATED", "terminated"),
        ]
    )
    result = baselines.no_change_baseline(share_2024, crosswalk_map)
    assert result["H0001-A"] == pytest.approx(0.3 * 1.25)
    assert result[OUTSIDE2] == pytest.approx(0.5 * 1.25)
    assert sum(result.values()) == pytest.approx(1.0)


def test_no_change_baseline_consolidated_plans_sum_onto_shared_successor():
    share_2024 = {"H0001-A": 0.1, "H0001-B": 0.15, OUTSIDE1: 0.75}
    crosswalk_map = predict.crosswalk_map_from_rows(
        [
            _row("H0001", "A", "H0001", "C", "consolidated"),
            _row("H0001", "B", "H0001", "C", "consolidated"),
        ]
    )
    result = baselines.no_change_baseline(share_2024, crosswalk_map)
    assert result["H0001-C"] == pytest.approx(0.25)
    assert sum(result.values()) == pytest.approx(1.0)


def test_no_change_baseline_sums_to_one_with_multiple_terminations():
    share_2024 = {"H-A": 0.2, "H-B": 0.1, "H-C": 0.1, OUTSIDE1: 0.6}
    crosswalk_map = predict.crosswalk_map_from_rows(
        [
            _row("H", "A", "H", "A", "renewed"),
            _row("H", "B", "TERMINATED", "TERMINATED", "terminated"),
            _row("H", "C", "TERMINATED", "TERMINATED", "terminated"),
        ]
    )
    result = baselines.no_change_baseline(share_2024, crosswalk_map)
    assert sum(result.values()) == pytest.approx(1.0)
    assert result["H-A"] == pytest.approx(0.2 / 0.8)
    assert result[OUTSIDE2] == pytest.approx(0.6 / 0.8)


# --- trend_baseline -----------------------------------------------------------------


def test_trend_baseline_extrapolates_linear_change():
    # A: 2023=0.10 -> 2024=0.20 -> trend 2025 = 0.20 + (0.20-0.10) = 0.30
    # outside absorbs the rest
    share_2024 = {"H0001-A": 0.20, OUTSIDE1: 0.80}
    share_2023 = {"H0001-A": 0.10, OUTSIDE1: 0.90}
    crosswalk_map = predict.crosswalk_map_from_rows([_row("H0001", "A", "H0001", "A", "renewed")])
    result = baselines.trend_baseline(share_2024, share_2023, crosswalk_map)
    # pre-crosswalk trend share for A is 0.30; crosswalk here is a no-op
    # (single renewed plan), so post-mapping share should still be 0.30
    assert result["H0001-A"] == pytest.approx(0.30)
    assert sum(result.values()) == pytest.approx(1.0)


def test_trend_baseline_clips_negative_extrapolation_at_zero():
    # A: 2023=0.30 -> 2024=0.05 -> raw trend = 0.05 + (0.05-0.30) = -0.20 -> clipped to 0
    share_2024 = {"H0001-A": 0.05, OUTSIDE1: 0.95}
    share_2023 = {"H0001-A": 0.30, OUTSIDE1: 0.70}
    crosswalk_map = predict.crosswalk_map_from_rows([_row("H0001", "A", "H0001", "A", "renewed")])
    result = baselines.trend_baseline(share_2024, share_2023, crosswalk_map)
    assert result["H0001-A"] == pytest.approx(0.0, abs=1e-9)
    assert sum(result.values()) == pytest.approx(1.0)


def test_trend_baseline_new_plan_in_2024_has_zero_2023_share():
    # "H0001-NEW" has no 2023 counterpart at all -> 2023 share defaults to 0
    # -> trend = 2024_share + (2024_share - 0) = 2*2024_share
    share_2024 = {"H0001-NEW": 0.10, OUTSIDE1: 0.90}
    share_2023 = {OUTSIDE1: 1.0}
    crosswalk_map = predict.crosswalk_map_from_rows([_row("H0001", "NEW", "H0001", "NEW", "renewed")])
    result = baselines.trend_baseline(share_2024, share_2023, crosswalk_map)
    assert result["H0001-NEW"] == pytest.approx(0.20)


def test_trend_baseline_renormalizes_after_clipping():
    # Force a clip so raw total != 1, confirm output still sums to 1.
    share_2024 = {"H-A": 0.05, "H-B": 0.90, OUTSIDE1: 0.05}
    share_2023 = {"H-A": 0.50, "H-B": 0.45, OUTSIDE1: 0.05}
    crosswalk_map = predict.crosswalk_map_from_rows(
        [_row("H", "A", "H", "A", "renewed"), _row("H", "B", "H", "B", "renewed")]
    )
    result = baselines.trend_baseline(share_2024, share_2023, crosswalk_map)
    assert sum(result.values()) == pytest.approx(1.0)
    assert result["H-A"] == pytest.approx(0.0, abs=1e-9)  # 0.05 + (0.05-0.50) = -0.40 -> clipped


# --- ensure_cpsc_2023_ingested / real download plumbing ---------------------------


def test_landing_page_2023_constant_exists_and_is_a_cms_url():
    from ingest import cpsc as cpsc_ingest

    assert cpsc_ingest.LANDING_PAGE_2023_03.startswith("https://www.cms.gov/")


@pytest.mark.integration
def test_real_cpsc_2023_ingest_and_parse_or_documented_unavailable():
    """Live network test: tries the real CMS download via the existing
    ingest framework (cache-first). Per the Phase 5 spec, a genuine
    structural failure (link not found, HTTP error) is an acceptable,
    documented outcome -- this test only fails on an *unexpected* exception
    type, not on the download itself being unavailable in this environment.
    """
    try:
        record = baselines.ensure_cpsc_2023_ingested()
    except (RuntimeError, OSError, httpx.HTTPError) as exc:  # documented "structurally unavailable" path
        # `httpx.HTTPError` is the base of every transport/protocol failure
        # httpx raises, and it is NOT an OSError -- so without it, a sandbox
        # or CI runner whose egress policy blocks www.cms.gov surfaces an
        # `httpx.ProxyError: 403 Forbidden` as a hard test ERROR rather than
        # the documented skip. "The network won't let us reach CMS" is
        # exactly the "structurally unavailable" case this path exists for.
        pytest.skip(f"2023 CPSC download structurally unavailable: {type(exc).__name__}: {exc}")
        return
    assert record.filename
    df = baselines.load_or_parse_cpsc_2023()
    assert isinstance(df, pd.DataFrame)
    assert set(["contract_id", "plan_id", "enrollment", "suppressed"]).issubset(df.columns)
    assert len(df) > 0
