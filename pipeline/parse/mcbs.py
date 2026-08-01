"""Parse: MCBS Survey File PUF (2023, Fall round) -> variable inventory + slimmed subset.

Source: ``data/raw_cache/mcbs/SFPUF2023_Data.zip`` (Survey File PUF; 3
seasonal rounds — fall/winter/summer) + ``SFPUF2023_Codebooks.zip``
(per-round variable codebooks). We use the **Fall** round: it's the primary
annual interview (345 columns, ~13K respondents) and, empirically, the only
round whose codebook contains the satisfaction/cost/health-status/MA-benefit
content this pipeline cares about (winter/summer are narrower topical
modules — verified by grepping all three codebooks).

This module does NOT build consumer segments (that's Phase 2). It:
  1. Parses the codebook text into (variable, label) pairs.
  2. Scans labels for keywords in 5 categories relevant to plan choice:
     price_sensitivity, benefit_importance, plan_switching_history,
     health_status, satisfaction. Writes the match set as JSON
     (data/interim/mcbs_variable_inventory.json).
  3. Slims the full CSV down to the union of matched candidate columns
     (capped at ~60) plus identifiers/weights, written to
     data/interim/mcbs_subset.parquet. The full CSV stays in raw_cache only.

Codebook text format (fixed-width-ish; verified against the real file):
variable *definition* lines start at column 0 ("VARNAME   FORMAT   [Q#]
Label..."); frequency-breakdown rows and "Notes:" lines are indented. We
distinguish the two by leading whitespace, then split on runs of 2+ spaces
(the column separator) and take the first token as the variable name and
the last token as the label.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd

from config.settings import settings

DATASET = "mcbs"
ROUND_LABEL = "1_fall"  # SFPUF2023_1_fall.{csv,xpt} — see module docstring.

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "price_sensitivity": [
        "premium", "cost", "afford", "pay ", "pay additional", "oop",
        "out-of-pocket", "copay", "co-pay", "deduct", "subsidy", "expense",
    ],
    "benefit_importance": [
        "benefit", "cover", "dental", "vision", "hearing", "drug", "rx",
        "important", "behavioral health", "nursing home", "inpatient",
    ],
    "plan_switching_history": [
        "switch", "disenroll", "change plan", "change in plan", "new plan",
        "enrolled in", "drop plan", "recommend",
    ],
    "health_status": [
        "general health", "health compared", "activities", "adl", "condition",
        "disab", "chronic", "functional",
    ],
    "satisfaction": [
        "satisf", "recommend", "quality of", "qual of", "ease ", "concern",
    ],
}

# Identifiers / survey weights always kept in the subset regardless of
# whether they matched a keyword category.
ALWAYS_KEEP_COLUMNS = ["PUF_ID", "SURVEYYR", "VERSION"]
PRIMARY_WEIGHT_COLUMN = "PUFFWGT"

_VARIABLE_LINE_RE = re.compile(r"^\S")


def parse_codebook(text: str) -> pd.DataFrame:
    records = []
    for line in text.splitlines():
        if not line or line[0].isspace():
            continue  # frequency rows / "Notes:" continuations are indented
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 2:
            continue
        variable, label = parts[0], parts[-1]
        if variable == "Variable":  # the codebook's own header row
            continue
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", variable):
            continue
        records.append({"variable": variable, "label": label.strip()})
    return pd.DataFrame.from_records(records, columns=["variable", "label"])


def build_inventory(codebook: pd.DataFrame) -> dict[str, list[dict[str, str]]]:
    inventory: dict[str, list[dict[str, str]]] = {cat: [] for cat in CATEGORY_KEYWORDS}
    for _, row in codebook.iterrows():
        label_lower = row["label"].lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in label_lower for kw in keywords):
                inventory[category].append({"variable": row["variable"], "label": row["label"]})
    return inventory


def select_candidate_columns(inventory: dict[str, list[dict[str, str]]], max_columns: int = 60) -> list[str]:
    seen: list[str] = []
    for variables in inventory.values():
        for entry in variables:
            if entry["variable"] not in seen:
                seen.append(entry["variable"])
    return seen[:max_columns]


def build_subset(raw_csv_bytes: bytes, columns: list[str], weight_columns: list[str]) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw_csv_bytes), dtype=str)
    keep = [c for c in (ALWAYS_KEEP_COLUMNS + columns + weight_columns) if c in df.columns]
    # de-dupe while preserving order
    seen = set()
    ordered = [c for c in keep if not (c in seen or seen.add(c))]
    return df[ordered]


def _read_zip_member(zip_path: Path, name_pattern: str) -> bytes:
    with zipfile.ZipFile(zip_path) as z:
        matches = [n for n in z.namelist() if re.search(name_pattern, n)]
        if not matches:
            raise RuntimeError(f"No entry matching {name_pattern!r} in {zip_path}")
        return z.read(matches[0])


def run(max_columns: int = 60) -> tuple[dict, pd.DataFrame]:
    codebook_zip = settings.RAW_CACHE_DIR / DATASET / "SFPUF2023_Codebooks.zip"
    data_zip = settings.RAW_CACHE_DIR / DATASET / "SFPUF2023_Data.zip"

    codebook_text = _read_zip_member(codebook_zip, rf"{re.escape(ROUND_LABEL)}\.txt$").decode("latin-1")
    codebook = parse_codebook(codebook_text)
    inventory = build_inventory(codebook)

    settings.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    inventory_path = settings.INTERIM_DIR / "mcbs_variable_inventory.json"
    inventory_path.write_text(json.dumps(inventory, indent=2))

    columns = select_candidate_columns(inventory, max_columns=max_columns)
    csv_bytes = _read_zip_member(data_zip, rf"sfpuf2023_{re.escape(ROUND_LABEL)}\.csv$")
    subset = build_subset(csv_bytes, columns, weight_columns=[PRIMARY_WEIGHT_COLUMN])
    subset.to_parquet(settings.INTERIM_DIR / "mcbs_subset.parquet", index=False)

    return inventory, subset


if __name__ == "__main__":
    inv, subset_df = run()
    for cat, vars_ in inv.items():
        print(f"{cat}: {len(vars_)} candidate variables")
    print(f"mcbs_subset: {subset_df.shape[0]} rows x {subset_df.shape[1]} columns")
