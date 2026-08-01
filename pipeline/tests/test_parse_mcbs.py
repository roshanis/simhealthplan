"""Tests for parse/mcbs.py — MCBS Survey File PUF variable inventory + subset.

TDD against small committed fixtures mirroring the real MCBS codebook text
format (fixed-width-ish: variable definitions start at column 0, frequency
breakdowns and "Notes:" lines are indented) and a matching data CSV slice.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from parse import mcbs

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_codebook_extracts_variable_definitions_only():
    text = (FIXTURES / "mcbs_codebook_sample.txt").read_text()
    df = mcbs.parse_codebook(text)

    assert list(df.columns) == ["variable", "label"]
    variables = set(df["variable"])
    assert "ACC_MCQUALTY" in variables
    assert "MA_MADVPAY" in variables
    assert "PUFFWGT" in variables
    # Header row and frequency/notes continuation lines must be excluded.
    assert "Variable" not in variables
    assert not any(v.replace(",", "").isdigit() for v in variables)

    row = df.set_index("variable").loc["HLT_GENHELTH"]
    assert row["label"] == "General health compared others same age"


def test_build_inventory_matches_keyword_categories():
    text = (FIXTURES / "mcbs_codebook_sample.txt").read_text()
    codebook = mcbs.parse_codebook(text)
    inventory = mcbs.build_inventory(codebook)

    assert set(inventory.keys()) == set(mcbs.CATEGORY_KEYWORDS.keys())
    satisfaction_vars = {v["variable"] for v in inventory["satisfaction"]}
    assert "ACC_MCQUALTY" in satisfaction_vars
    assert "MA_RECMADV" in satisfaction_vars

    price_vars = {v["variable"] for v in inventory["price_sensitivity"]}
    assert "ACC_HCDELAY" in price_vars or "MA_MADVPAY" in price_vars

    health_vars = {v["variable"] for v in inventory["health_status"]}
    assert "HLT_GENHELTH" in health_vars


def test_select_candidate_columns_returns_deduped_list():
    text = (FIXTURES / "mcbs_codebook_sample.txt").read_text()
    codebook = mcbs.parse_codebook(text)
    inventory = mcbs.build_inventory(codebook)
    columns = mcbs.select_candidate_columns(inventory, max_columns=60)

    assert len(columns) == len(set(columns))  # no duplicates
    assert "ACC_MCQUALTY" in columns


def test_build_subset_keeps_only_selected_and_weight_columns():
    raw = (FIXTURES / "mcbs_data_sample.csv").read_bytes()
    columns = ["PUF_ID", "ACC_MCQUALTY", "MA_MADVPAY"]
    df = mcbs.build_subset(raw, columns, weight_columns=["PUFFWGT"])

    # ALWAYS_KEEP_COLUMNS (PUF_ID/SURVEYYR/VERSION, whichever are present)
    # + the requested candidate columns + weight columns.
    assert {"PUF_ID", "SURVEYYR", "ACC_MCQUALTY", "MA_MADVPAY", "PUFFWGT"} <= set(df.columns)
    assert "UNRELATED_COL" not in df.columns
    assert len(df) == 3
