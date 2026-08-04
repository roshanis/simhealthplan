/**
 * The Phase 7 leadership report: verdict, share-shift chart, persona
 * cards, market snapshot, evaluation diagnostics, and methodology, in that
 * order. Server component
 * -- every artifact below is a build-time static import (`lib/data/loaders.ts`),
 * so this route renders fully server-side with zero request-time I/O and
 * zero environment variables required.
 *
 * Chart-form note (ShareShiftChart): hand-rolled SVG rather than Recharts.
 * Recharts' grouped/composed-chart primitives are built around one series
 * per array of {x,y} points rendered independently; this chart needed one
 * connector line PER ROW between two points from two different series, a
 * third muted reference tick per row, and a full-row (not just per-dot)
 * hover/focus target with a custom multi-value tooltip. That's readily
 * expressible as a dumbbell plot hand-rolled in SVG (React owns the DOM,
 * no imperative chart library state to fight) but awkward to compose from
 * Recharts' <Line>/<Scatter>/<ReferenceLine> building blocks without
 * fighting its per-series data model. Recharts was not added as a
 * dependency for this one chart as a result -- noted here per the task's
 * "note it" instruction.
 */

import Link from "next/link";

import { DiagnosticsPanel } from "@/components/report/DiagnosticsPanel";
import { LiveLlmButton } from "@/components/report/LiveLlmButton";
import { MarketSnapshot } from "@/components/report/MarketSnapshot";
import { Methodology } from "@/components/report/Methodology";
import { PersonaCards } from "@/components/report/PersonaCards";
import { PhysicianSupply } from "@/components/report/PhysicianSupply";
import { ShareShiftChart } from "@/components/report/ShareShiftChart";
import { VerdictSection } from "@/components/report/VerdictSection";
import { archetypesDisplay, backtest, diagnostics, market, personas } from "@/lib/data/loaders";
import { formatCount } from "@/lib/format";
import { buildMarketFacts } from "@/lib/report/marketFacts";
import { buildPersonaCards, buildPersonaLookup, buildPlanLookup } from "@/lib/report/personas";
import { bestNaiveVariant, buildShareShiftRows } from "@/lib/report/shareShift";

const AGE_BAND_DISPLAY_ORDER = ["65-69 years", "70-74 years", "75-84 years", "85+"];

export default function ReportPage() {
  const summary = backtest.summary;
  const naiveVariant = bestNaiveVariant(summary);
  const shareShiftRows = buildShareShiftRows(backtest.per_plan, naiveVariant, 15);
  const namedPlanRowCount = shareShiftRows.filter((row) => !row.isAggregate).length;

  const plansByKey = buildPlanLookup(market.plans["2024"] ?? []);
  const personaByArchetypeId = buildPersonaLookup(personas.personas);
  const personaCards = buildPersonaCards(archetypesDisplay.archetypes, plansByKey, personaByArchetypeId);

  const segments = [...new Set(personaCards.map((c) => c.segmentLabel))].sort();
  const ageBands = AGE_BAND_DISPLAY_ORDER.filter((band) => personaCards.some((c) => c.ageBandLabel === band));

  const marketFacts = buildMarketFacts(market);
  const years = Object.keys(market.plans).sort();

  const liveLlmEnabled = process.env.ENABLE_LIVE_LLM === "true";

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-16 px-4 py-10 sm:px-8">
      <header className="flex flex-col gap-4">
        <nav className="flex items-center justify-between text-sm" style={{ color: "var(--text-secondary)" }}>
          <span className="font-semibold" style={{ color: "var(--text-primary)" }}>
            simhealthplan
          </span>
          <div className="flex items-center gap-2">
            <Link href="/network" className="rounded-md border px-3 py-1.5" style={{ borderColor: "var(--border)" }}>
              Design a network →
            </Link>
            <Link href="/scenario" className="rounded-md border px-3 py-1.5" style={{ borderColor: "var(--border)" }}>
              Try a what-if scenario →
            </Link>
          </div>
        </nav>
        <div className="flex flex-col gap-3">
          <p className="text-xs font-medium uppercase tracking-wide" style={{ color: "var(--text-secondary)" }}>
            Maricopa County, AZ · 2024 → 2025
          </p>
          <h1 className="text-4xl font-semibold tracking-tight" style={{ color: "var(--text-primary)" }}>
            A Medicare plan-choice model, tested against real enrollment
          </h1>
          <p className="max-w-3xl text-base" style={{ color: "var(--text-secondary)" }}>
            {/* The archetypes are 2024-anchored (IPF against 2024 ACS marginals -- see Methodology), so the
                "modeled as N archetypes" population figure must come from that same 2024 cohort, not the 2025
                market (790,307 eligibles, ~2.4% larger). Deriving straight from `archetypes.json`'s own metadata
                -- rather than reaching into `market.json`'s 2024 total, which merely happens to match today --
                means this sentence can never drift out of sync with what the archetypes actually sum to, even if
                a future data refresh changes the 2024 market total independently of the archetype weights. */}
            {formatCount(archetypesDisplay.metadata.population_total ?? market.market_totals["2024"]?.eligibles ?? 0)}{" "}
            synthetic Medicare-eligible beneficiaries, modeled as {archetypesDisplay.metadata.archetype_count} weighted
            archetypes, choosing among {market.market_totals["2024"]?.plan_count} (2024) →{" "}
            {market.market_totals["2025"]?.plan_count} (2025) real Medicare Advantage plans -- backtested against
            actual CMS enrollment.
          </p>
        </div>
        <ol className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            {
              step: "1",
              title: "Build a population",
              body: `${archetypesDisplay.metadata.archetype_count} representative profiles, built from Census and Medicare survey data, stand in for the county's Medicare-eligible residents.`,
            },
            {
              step: "2",
              title: "Simulate their choices",
              body: `Each profile picks among the county's real plans (${market.market_totals["2024"]?.plan_count} in 2024, ${market.market_totals["2025"]?.plan_count} in 2025) based on premium, benefits, and the plan they already had.`,
            },
            {
              step: "3",
              title: "Check against reality",
              body: "The predicted enrollment shifts are scored against actual CMS enrollment data, alongside two simple baselines.",
            },
          ].map((item) => (
            <li
              key={item.step}
              className="flex flex-col gap-1 rounded-xl border p-4"
              style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
            >
              <span className="text-xs font-semibold" style={{ color: "var(--text-muted)" }}>
                Step {item.step}
              </span>
              <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                {item.title}
              </span>
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                {item.body}
              </span>
            </li>
          ))}
        </ol>
      </header>

      <VerdictSection summary={summary} />

      <section aria-labelledby="share-shift-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="share-shift-heading" className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
            Predicted vs. actual, plan by plan
          </h2>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            Each row is one plan: how much the model predicted its market share would change from 2024 to 2025 (blue)
            next to what actually happened (green). Shown for the {namedPlanRowCount} largest plans by 2024 enrollment
            {shareShiftRows.length > namedPlanRowCount ? ", with all remaining plans combined into one row" : ""}. The
            gray tick marks the simple baseline ({naiveVariant === "no_change" ? "assume nothing changes" : "extend last year's trend"}) for comparison.
          </p>
        </div>
        <ShareShiftChart rows={shareShiftRows} bestNaive={naiveVariant} />
      </section>

      <section aria-labelledby="personas-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="personas-heading" className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
            The simulated population
          </h2>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            The {archetypesDisplay.metadata.archetype_count} profiles behind the simulation, built from Census
            demographics and national Medicare survey data. Each card is one profile — expand it to see who it
            represents and which plans that group has historically chosen.
          </p>
          {liveLlmEnabled && <LiveLlmButton />}
        </div>
        <PersonaCards
          cards={personaCards}
          personasAvailable={personas.available}
          segments={segments}
          ageBands={ageBands}
        />
      </section>

      <section aria-labelledby="market-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="market-heading" className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
            The plans they chose from
          </h2>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            Every Medicare Advantage plan offered in Maricopa County in 2024 and 2025, from CMS&rsquo;s published plan
            files. Sort any column or switch years.
          </p>
        </div>
        <MarketSnapshot plansByYear={market.plans} facts={marketFacts} years={years} />
      </section>

      {/* Placed directly before Methodology, not up near the verdict: this panel
          quantifies exactly the compromises Methodology documents qualitatively
          (e.g. the "coefficient-jitter" item explains the p10/p50/p90 bounds are a
          heuristic, not a formal confidence interval -- Finding 1 below is how badly
          that heuristic under-covers in practice). Reading the quantified failure
          right before the methodological explanation of why is the natural order. */}
      <DiagnosticsPanel diagnostics={diagnostics} />

      <Methodology />

      <footer className="border-t pt-6 text-xs" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
        Built from public CMS and Census data. All results are reproducible (fixed random seed). You can also{" "}
        <Link href="/scenario" className="underline">
          try a what-if scenario
        </Link>{" "}
        — change a real plan&rsquo;s premium or benefits and see how the model expects enrollment to respond.
      </footer>
    </div>
  );
}
