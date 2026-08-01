.PHONY: test pipeline-test app-test app-build ingest archetypes calibrate personas backtest export

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

## --- Later-phase placeholders (not implemented yet) ---

## Export trimmed, UI-ready JSON bundles from data/processed into app/src/data.
export:
	cd pipeline && uv run python -m export.export_artifacts
