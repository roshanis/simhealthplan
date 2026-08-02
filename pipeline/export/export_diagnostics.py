"""Exports `data/processed/backtest_diagnostics.json` into the app as
`app/src/data/diagnostics.json` (``make export-diagnostics``).

Deliberately a SEPARATE entrypoint from `export_artifacts.build_all()`
rather than a seventh artifact inside it. `build_all()` opens by resolving
`choice_model.predict.load_crosswalk_map()`, which reads
`data/interim/plan_crosswalk_2024_2025.parquet` -- a gitignored file only
`make ingest` can produce, which in turn needs network access to CMS. So
`build_all()` cannot run at all in a fresh clone or a network-restricted
environment, and folding the diagnostics into it would inherit that
dependency for no reason: the diagnostics are a pure function of the
committed `backtest_diagnostics.json`, which is a pure function of the
committed `backtest_result.json`. Keeping them separate means the report's
diagnostics panel can be regenerated anywhere.

The source artifact is already small (~24KB), so this trims only the parts
the UI has no use for -- the full 21-point lambda sweep is kept (the report
plots it), while per-plan coverage flags for all 95 keys are dropped in
favour of the aggregate counts the panel actually renders.
"""

from __future__ import annotations

import json
from pathlib import Path

from config.settings import settings
from export.export_artifacts import APP_DATA_DIR, MAX_ARTIFACT_BYTES, _load_json, _write_json

SOURCE_FILENAME = "backtest_diagnostics.json"
DEST_FILENAME = "diagnostics.json"

# Top-level `coverage` keys the report panel renders. `plan_level` and
# `outside_option` carry per-plan detail the panel summarises rather than
# lists, so only their aggregate fields survive the trim below.
_COVERAGE_SCALAR_KEYS = (
    "nominal_coverage",
    "nominal_interval",
    "calibration_tolerance",
    "verdict_unweighted",
    "verdict_weighted",
    "asymmetry_note",
)


def _trim_coverage(coverage: dict) -> dict:
    """Keeps the verdicts, the nominal target, and the aggregate hit/miss
    counts -- everything the panel needs to say "17 of 94 plans (18.1%) fell
    inside a nominal 80% band, and the misses skew high" -- while dropping
    any per-plan arrays, which the panel never enumerates."""
    trimmed = {key: coverage[key] for key in _COVERAGE_SCALAR_KEYS if key in coverage}
    for section in ("plan_level", "reconciliation"):
        block = coverage.get(section)
        if isinstance(block, dict):
            trimmed[section] = {
                key: value for key, value in block.items() if not isinstance(value, (list, dict))
            }
    return trimmed


def build_diagnostics(diagnostics_file: dict) -> dict:
    """Shapes the processed diagnostics artifact for the app.

    Structure is preserved (same key names as `data/processed/
    backtest_diagnostics.json`) so the report's TypeScript types read as a
    subset of the Python artifact rather than a renamed parallel schema.
    """
    damping = diagnostics_file["damping"]
    decomposition = diagnostics_file["error_decomposition"]

    return {
        "coverage": _trim_coverage(diagnostics_file["coverage"]),
        "damping": {
            "predictor": damping["predictor"],
            "lambda_grid": damping["lambda_grid"],
            "sweep": damping["sweep"],
            "oracle": damping["oracle"],
            "leave_one_plan_out_cv": damping["leave_one_plan_out_cv"],
            "endpoints": damping["endpoints"],
            "verdict": damping["verdict"],
        },
        "error_decomposition": {
            "n_plans_scored": decomposition["n_plans_scored"],
            "total_weighted_mae_reconstructed": decomposition["total_weighted_mae_reconstructed"],
            "top_contributors": decomposition["top_contributors"],
            "n_plans_to_reach_cumulative_share": decomposition["n_plans_to_reach_cumulative_share"],
            "new_entrant_vs_incumbent_split": decomposition["new_entrant_vs_incumbent_split"],
            "org_rollup": decomposition["org_rollup"],
        },
        "metadata": diagnostics_file["metadata"],
    }


def build(processed_dir: Path | None = None, app_data_dir: Path | None = None) -> dict:
    """Reads the committed diagnostics artifact, trims it, and writes
    `diagnostics.json` into the app's data directory. Returns the written
    payload."""
    src_dir = processed_dir if processed_dir is not None else settings.PROCESSED_DIR
    dest_dir = app_data_dir if app_data_dir is not None else APP_DATA_DIR

    source_path = src_dir / SOURCE_FILENAME
    if not source_path.exists():
        raise FileNotFoundError(
            f"{source_path} not found -- run `make diagnostics` first "
            "(it needs only data/processed/backtest_result.json, no network access)."
        )

    payload = build_diagnostics(_load_json(source_path))
    size = _write_json(dest_dir / DEST_FILENAME, payload)
    if size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"{DEST_FILENAME} is {size} bytes, over MAX_ARTIFACT_BYTES ({MAX_ARTIFACT_BYTES})")
    return payload


if __name__ == "__main__":
    result = build()
    coverage = result["coverage"]["plan_level"]
    print(f"wrote {APP_DATA_DIR / DEST_FILENAME}")
    print(f"  coverage verdict:   {result['coverage']['verdict_unweighted']}")
    print(f"  damping verdict:    {result['damping']['verdict'].get('summary', result['damping']['verdict'])}")
    print(f"  top contributor:    {result['error_decomposition']['top_contributors'][0]['plan_key']}")
    print(f"  plan-level coverage keys: {sorted(coverage)}")
