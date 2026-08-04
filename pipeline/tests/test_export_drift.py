"""Export-drift gate: guards against `data/processed/*.json` and the
committed `app/src/data/*.json` UI artifacts silently diverging.

`export.export_artifacts.build_all` is the ONLY thing that is supposed to
produce `app/src/data/*.json` (see `make export`). This test regenerates
those six artifacts into a temp directory from the real committed
`data/processed/*.json` (+ `data/interim/plan_crosswalk_2024_2025.parquet`)
and asserts the result is byte-identical to what's actually committed under
`app/src/data/` -- i.e. that someone hand-edited `app/src/data/*.json`, or
edited `data/processed/*.json`/`export_artifacts.py` without re-running
`make export`, would fail this test.

No field is excluded from the comparison: `_write_json` writes with
`sort_keys=True` and a fixed 2-space indent, and every artifact's contents
(including `backtest.json`'s `metadata.generated_from` content-hash map and
`coefficients.json`'s `metadata.generated_from` block) are pure functions of
the source files' bytes -- there is no wall-clock timestamp or other
nondeterministic field anywhere in the six exported artifacts, so a plain
byte-for-byte comparison is exact and correct here.

Skips cleanly (not a failure) when the data this test needs isn't present:
  * `data/processed/*.json` absent -- nothing to regenerate from.
  * `data/interim/plan_crosswalk_2024_2025.parquet` absent -- `build_all`
    unconditionally reads this (via `choice_model.predict.load_crosswalk_map`)
    even though only `scenario_inputs.json` uses it. It's produced by
    `make ingest`, which needs network access to CMS/Census hosts -- not
    available in every environment (e.g. this one), and this test must not
    try to download it.
"""

from __future__ import annotations

import json

import pytest

from choice_model.predict import CROSSWALK_FILENAME
from config.settings import settings
from export import export_artifacts

REQUIRED_PROCESSED_FILES = (
    f"plans_{settings.YEAR1}.json",
    f"plans_{settings.YEAR2}.json",
    "archetypes.json",
    "coefficients.json",
    "backtest_result.json",
)

CROSSWALK_PATH = settings.INTERIM_DIR / CROSSWALK_FILENAME


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory) -> dict[str, dict]:
    missing_processed = [
        name for name in REQUIRED_PROCESSED_FILES if not (settings.PROCESSED_DIR / name).exists()
    ]
    if missing_processed:
        pytest.skip(
            f"data/processed/ missing {missing_processed}; run the pipeline stages "
            "(`make archetypes calibrate backtest`) first"
        )
    if not CROSSWALK_PATH.exists():
        pytest.skip(
            f"{CROSSWALK_PATH} not present; `export.export_artifacts.build_all` requires it "
            "(via choice_model.predict.load_crosswalk_map) even though only scenario_inputs.json "
            "uses it. Produced by `make ingest`, which needs network access to CMS/Census hosts "
            "-- not available in every environment. Not attempting to download it here."
        )

    dest_dir = tmp_path_factory.mktemp("export_drift")
    return export_artifacts.build_all(app_data_dir=dest_dir)


@pytest.mark.parametrize(
    "filename",
    ["market.json", "backtest.json", "archetypes.json", "coefficients.json", "scenario_inputs.json", "personas.json"],
)
def test_committed_app_artifact_matches_fresh_export(regenerated, filename):
    committed_path = export_artifacts.APP_DATA_DIR / filename
    assert committed_path.exists(), f"{committed_path} not committed; run `make export` and commit its output"

    expected_text = json.dumps(regenerated[filename], indent=2, sort_keys=True) + "\n"
    committed_text = committed_path.read_text()

    assert committed_text == expected_text, (
        f"{committed_path} has drifted from what `export.export_artifacts.build_all` produces "
        f"from the current data/processed/*.json -- run `make export` and commit the result."
    )
