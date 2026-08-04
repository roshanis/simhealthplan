/**
 * Single point of truth for loading the build-time JSON artifacts in
 * `app/src/data/` (written by `pipeline/export/export_artifacts.py`, plus
 * `diagnostics.json` from the separate `pipeline/export/export_diagnostics.py`;
 * see `types.ts` for their shapes). Every artifact is a **static ES import**,
 * not an `fs` read -- Next.js inlines these into the server bundle at build
 * time, so both the report page (server component) and the `/api/scenario`
 * route handler read the same in-memory object with zero request-time I/O.
 *
 * `personas.json` and (if/when it exists) `y2_predictions.json` are the two
 * artifacts explicitly allowed to be absent/pending -- `personas.json` is
 * always exported (with `available: false` until `make personas` runs), so
 * it's imported unconditionally like everything else; callers branch on
 * `.available`, never on file-existence.
 */

import archetypesRaw from "@/data/archetypes.json";
import backtestRaw from "@/data/backtest.json";
import coefficientsRaw from "@/data/coefficients.json";
import diagnosticsRaw from "@/data/diagnostics.json";
import marketRaw from "@/data/market.json";
import personasRaw from "@/data/personas.json";
import scenarioInputsRaw from "@/data/scenario_inputs.json";
import type { CoefficientsFile } from "@/lib/choice-model/types";
import type {
  ArchetypesDisplayFile,
  BacktestData,
  DiagnosticsFile,
  MarketData,
  PersonasFile,
  ScenarioInputsFile,
} from "@/lib/data/types";

export const market = marketRaw as unknown as MarketData;
export const backtest = backtestRaw as unknown as BacktestData;
export const archetypesDisplay = archetypesRaw as unknown as ArchetypesDisplayFile;
export const coefficients = coefficientsRaw as unknown as CoefficientsFile;
export const personas = personasRaw as unknown as PersonasFile;
export const scenarioInputs = scenarioInputsRaw as unknown as ScenarioInputsFile;
// `diagnostics.json` (`make export-diagnostics`) is always exported alongside the
// other Phase 7 artifacts -- unlike `personas.json` it has no `available` flag to
// branch on, so it's imported unconditionally like `market`/`backtest` above.
export const diagnostics = diagnosticsRaw as unknown as DiagnosticsFile;
