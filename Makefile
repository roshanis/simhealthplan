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

## --- Later-phase placeholders (not implemented yet) ---

archetypes:
	@echo "archetypes: not implemented yet"

calibrate:
	@echo "calibrate: not implemented yet"

personas:
	@echo "personas: not implemented yet"

backtest:
	@echo "backtest: not implemented yet"

export:
	@echo "export: not implemented yet"
