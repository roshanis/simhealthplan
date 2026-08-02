/**
 * The Phase 7 leadership report: verdict, share-shift chart, persona
 * cards, market snapshot, and methodology, in that order. Server component
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

import { LiveLlmButton } from "@/components/report/LiveLlmButton";
import { MarketSnapshot } from "@/components/report/MarketSnapshot";
import { Methodology } from "@/components/report/Methodology";
import { PersonaCards } from "@/components/report/PersonaCards";
import { ShareShiftChart } from "@/components/report/ShareShiftChart";
import { VerdictSection } from "@/components/report/VerdictSection";
import { archetypesDisplay, backtest, market, personas } from "@/lib/data/loaders";
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
          <Link href="/scenario" className="rounded-md border px-3 py-1.5" style={{ borderColor: "var(--border)" }}>
            Live scenario demo →
          </Link>
        </nav>
        <div className="flex flex-col gap-3">
          <p className="text-xs font-medium uppercase tracking-wide" style={{ color: "var(--text-secondary)" }}>
            Medicare Advantage plan-design pilot · Maricopa County, AZ · 2024 → 2025
          </p>
          <h1 className="text-4xl font-semibold tracking-tight" style={{ color: "var(--text-primary)" }}>
            Did a persona-grounded choice model predict last AEP&rsquo;s actual plan-share shifts?
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
      </header>

      <VerdictSection summary={summary} />

      <section aria-labelledby="share-shift-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="share-shift-heading" className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
            Where the model called it right (and wrong)
          </h2>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            The {namedPlanRowCount} plans with the largest 2024 enrollment
            {shareShiftRows.length > namedPlanRowCount ? ", plus every remaining plan aggregated into one row" : ""}.
            Each row compares the model&rsquo;s predicted 2024→2025 share shift against what actually happened, with
            the best naive baseline ({naiveVariant === "no_change" ? "no change" : "trend"}) shown as a reference
            tick.
          </p>
        </div>
        <ShareShiftChart rows={shareShiftRows} bestNaive={naiveVariant} />
      </section>

      <section aria-labelledby="personas-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="personas-heading" className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
            Meet the market
          </h2>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            {archetypesDisplay.metadata.archetype_count} weighted synthetic archetypes stand in for Maricopa
            County&rsquo;s Medicare-eligible population -- built from Census ACS demographics and national MCBS
            attitude segments (see Methodology for what that does and doesn&rsquo;t capture).
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
            The world the personas live in
          </h2>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            The full Maricopa County Medicare Advantage roster both years, sourced from CMS Landscape + PBP benefits
            files.
          </p>
        </div>
        <MarketSnapshot plansByYear={market.plans} facts={marketFacts} years={years} />
      </section>

      <Methodology />

      <footer className="border-t pt-6 text-xs" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
        Public CMS/Census data only. Fixed seed (42) throughout. See{" "}
        <Link href="/scenario" className="underline">
          the live scenario demo
        </Link>{" "}
        to run counterfactual plan-design changes against this same model.
      </footer>
    </div>
  );
}
