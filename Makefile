.PHONY: test pipeline-test app-test app-build ingest archetypes calibrate personas backtest diagnostics export export-diagnostics golden

## Run the full test suite (pipeline + app)
test: pipeline-test app-test

## Run pipeline (pytest) tests
pipeline-test:
	cd pipeline && uv run pytest

## Run app (vitest) tests
app-test:
	cd app && npm test -- --run

## Build the Next.js app
app-build:
	cd app && npm run build

## --- Pipeline stages ---

## Download all Phase 1 source data (cache-first, idempotent) and parse it
## into validated Maricopa-focused interim tables (data/interim/*.parquet).
ingest:
	cd pipeline && uv run python -m ingest.run_all
	cd pipeline && uv run python -m parse.run_all

## Build synthetic-population archetypes (data/processed/archetypes.json)
## from Phase 1 interim data.
archetypes:
	cd pipeline && uv run python -m archetypes.build_archetypes

## Build the Phase 3 choice model: canonical per-plan attribute tables
## (data/processed/plans_2024.json, plans_2025.json) and the calibrated
## Year-1 multinomial-logit coefficients (data/processed/coefficients.json).
calibrate:
	cd pipeline && uv run python -m choice_model.plan_attributes
	cd pipeline && uv run python -m choice_model.calibrate

## Build the Phase 4 LLM persona layer: for each of the 80 archetypes, one
## CHOICE call + one BACKSTORY call (cache-first, budget-capped) blended
## with the Phase 3 Year-2 logit baseline. Writes data/processed/personas.json
## and data/processed/y2_predictions.json. Requires OPENAI_API_KEY in
## pipeline/.env on a cold cache; a warm cache needs no key at all.
personas:
	cd pipeline && uv run python -m llm.run_persona_pass

## Build the Phase 5 backtest: scores the Year-2 logit prediction (and the
## blended prediction, once `make personas` has run) against actual 2025
## CMS enrollment, alongside two naive baselines (no_change, trend), plus
## Monte Carlo p10/p50/p90 confidence bounds. Writes
## data/processed/backtest_result.json.
backtest:
	cd pipeline && uv run python -m backtest.run_backtest

## Post-hoc scoring diagnostics over data/processed/backtest_result.json:
## Monte Carlo p10/p90 coverage calibration, the lambda-damped shrinkage
## sweep (oracle + leave-one-plan-out CV), and the per-plan decomposition of
## the size-weighted MAE. Writes data/processed/backtest_diagnostics.json.
## Reads ONLY the committed backtest result -- no data/interim/ dependency,
## so unlike `backtest` this re-runs anywhere without `make ingest`.
diagnostics:
	cd pipeline && uv run python -m backtest.diagnostics

## Export the diagnostics artifact into the app (app/src/data/diagnostics.json)
## for the report's evaluation-diagnostics panel. Kept separate from `export`
## on purpose: `export` needs the data/interim/ crosswalk (see below) and so
## cannot run in a fresh clone, whereas this reads only
## data/processed/backtest_diagnostics.json and always can.
export-diagnostics:
	cd pipeline && uv run python -m export.export_diagnostics

## --- Phase 6/7: export & parity fixtures ---

## Export the committed data/processed/*.json artifacts into six small,
## deterministic, UI-ready JSON files under app/src/data/ (market.json,
## backtest.json, archetypes.json, coefficients.json, scenario_inputs.json,
## personas.json). NOTE: in addition to data/processed/*.json, this also
## reads data/interim/plan_crosswalk_2024_2025.parquet (via
## choice_model.predict.load_crosswalk_map, needed for scenario_inputs.json)
## -- if `make ingest` hasn't been run to produce that file, this fails with
## a FileNotFoundError rather than silently skipping. `make ingest` needs
## network access to CMS/Census hosts, so this target cannot succeed in a
## network-restricted environment/clone until that file has been produced
## elsewhere and placed at data/interim/plan_crosswalk_2024_2025.parquet.
export:
	cd pipeline && uv run python -m export.export_artifacts

## Regenerate the Python <-> TypeScript golden parity fixture
## (shared/golden/parity_fixture.json), consumed by both
## pipeline/tests/test_golden_parity.py and app/tests/parity.test.ts to keep
## the TS choice-model port (app/src/lib/choice-model/) numerically
## identical to the Python original. Deliberately kept as its own target
## rather than folded into `export`: it writes to shared/golden/, not
## app/src/data/, and it only reads data/processed/{coefficients,
## archetypes,plans_2025}.json -- no data/interim/ crosswalk dependency --
## so it can regenerate even when `export` cannot (e.g. before `make
## ingest` has ever been run, or in a network-restricted environment).
golden:
	cd pipeline && uv run python -m export.golden_fixture
