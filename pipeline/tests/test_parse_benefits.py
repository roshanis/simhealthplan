"""Tests for parse/benefits.py — PBP Benefits targeted extract (5 flags + MOOP).

TDD against small committed fixtures mirroring the real PBP tab-delimited
files, INCLUDING the known CY2024 -> CY2025 schema break in the dental file
(CY2024 has one summary Y/N flag; CY2025 drops it in favor of per-sub-benefit
Y/N fields with no summary — see parse/benefits.py module docstring).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from parse import benefits

FIXTURES = Path(__file__).parent / "fixtures"

MARICOPA_KEYS = {("H0028", "023", "0"), ("H0028", "027", "0"), ("H0302", "001", "0"), ("H0710", "005", "0")}


def test_extract_dental_2024_style_uses_summary_flag():
    raw = (FIXTURES / "pbp_b16_dental_2024style.tsv").read_bytes()
    result = benefits.extract_dental(raw, MARICOPA_KEYS)
    assert result[("H0028", "023", "0")] is True
    assert result[("H0028", "027", "0")] is False
    assert ("H9999", "001", "0") not in result  # not a Maricopa key, filtered out


def test_extract_dental_2025_style_uses_any_subfield_heuristic():
    raw = (FIXTURES / "pbp_b16_dental_2025style.tsv").read_bytes()
    result = benefits.extract_dental(raw, MARICOPA_KEYS)
    assert result[("H0028", "023", "0")] is True  # maxenr_pv_yn == 1
    assert result[("H0028", "027", "0")] is False  # all sub-flags == 2


def test_extract_vision_true_if_either_exam_or_eyewear_covered():
    raw = (FIXTURES / "pbp_b17_vision_sample.tsv").read_bytes()
    result = benefits.extract_vision(raw, MARICOPA_KEYS)
    assert result[("H0028", "023", "0")] is True  # exam only
    assert result[("H0028", "027", "0")] is True  # eyewear only
    assert result[("H0302", "001", "0")] is False  # neither


def test_extract_hearing_aids_uses_b18b_not_b18a():
    raw = (FIXTURES / "pbp_b18_hearing_sample.tsv").read_bytes()
    result = benefits.extract_hearing(raw, MARICOPA_KEYS)
    assert result[("H0028", "023", "0")] is True
    assert result[("H0028", "027", "0")] is False  # exam covered but not aids


def test_extract_otc_or_flex():
    raw = (FIXTURES / "pbp_b13_otc_sample.tsv").read_bytes()
    result = benefits.extract_otc(raw, MARICOPA_KEYS)
    assert result[("H0028", "023", "0")] is True
    assert result[("H0028", "027", "0")] is False


def test_load_manual_fallback():
    df = benefits.load_manual_fallback(FIXTURES / "manual_benefit_fallback_sample.csv")
    row = df.set_index(["year", "contract_id", "plan_id", "segment_id"]).loc[(2024, "H0710", "005", "0")]
    assert row["has_comprehensive_dental"] == True  # noqa: E712
    assert row["has_hearing_aids"] == False  # noqa: E712


def test_apply_manual_fallback_fills_missing_plans_only():
    # H0710-005 is in MARICOPA_KEYS but absent from every PBP fixture above
    # (simulating an unparseable plan) -> must be filled from the manual CSV.
    dental = benefits.extract_dental((FIXTURES / "pbp_b16_dental_2024style.tsv").read_bytes(), MARICOPA_KEYS)
    vision = benefits.extract_vision((FIXTURES / "pbp_b17_vision_sample.tsv").read_bytes(), MARICOPA_KEYS)
    hearing = benefits.extract_hearing((FIXTURES / "pbp_b18_hearing_sample.tsv").read_bytes(), MARICOPA_KEYS)
    otc = benefits.extract_otc((FIXTURES / "pbp_b13_otc_sample.tsv").read_bytes(), MARICOPA_KEYS)
    moop = {k: 5000.0 for k in MARICOPA_KEYS}

    df = benefits.assemble(
        plan_keys=MARICOPA_KEYS,
        dental=dental, vision=vision, hearing=hearing, otc=otc, moop=moop, year=2024,
    )
    fallback = benefits.load_manual_fallback(FIXTURES / "manual_benefit_fallback_sample.csv")
    df = benefits.apply_manual_fallback(df, fallback)

    row = df.set_index(["contract_id", "plan_id", "segment_id"]).loc[("H0710", "005", "0")]
    assert row["has_comprehensive_dental"] == True  # noqa: E712
    assert row["has_vision"] == True  # noqa: E712
    assert row["source"] == "manual_fallback"

    # a plan resolved by auto-parse must NOT be touched by the fallback.
    auto_row = df.set_index(["contract_id", "plan_id", "segment_id"]).loc[("H0028", "023", "0")]
    assert auto_row["source"] == "auto"


def test_coverage_rate_and_uncovered_plans():
    dental = benefits.extract_dental((FIXTURES / "pbp_b16_dental_2024style.tsv").read_bytes(), MARICOPA_KEYS)
    vision = benefits.extract_vision((FIXTURES / "pbp_b17_vision_sample.tsv").read_bytes(), MARICOPA_KEYS)
    hearing = benefits.extract_hearing((FIXTURES / "pbp_b18_hearing_sample.tsv").read_bytes(), MARICOPA_KEYS)
    otc = benefits.extract_otc((FIXTURES / "pbp_b13_otc_sample.tsv").read_bytes(), MARICOPA_KEYS)
    moop = {k: 5000.0 for k in MARICOPA_KEYS}

    df = benefits.assemble(
        plan_keys=MARICOPA_KEYS, dental=dental, vision=vision, hearing=hearing, otc=otc, moop=moop, year=2024,
    )
    rate = benefits.coverage_rate(df)
    uncovered = benefits.uncovered_plans(df)
    # H0710-005 and H0302-001 are missing from at least one of the 4 source
    # files before fallback is applied.
    assert rate < 1.0
    assert ("H0710", "005", "0") in uncovered
