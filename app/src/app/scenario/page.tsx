/**
 * Live scenario demo: pick a 2025 plan, adjust its attributes, and see the
 * choice model's recomputed shares. The baseline (unmodified) shares are
 * computed once here, server-side, at build time (this page has no
 * per-request input, so Next statically prerenders it) -- only the
 * counterfactual recompute round-trips through `/api/scenario`.
 */

import Link from "next/link";

import { ScenarioDemo } from "@/components/scenario/ScenarioDemo";
import { coefficients, scenarioInputs } from "@/lib/data/loaders";
import { aggregateWeightedShares } from "@/lib/scenario/runScenario";
import type { Archetype, Plan } from "@/lib/choice-model/types";

export const metadata = {
  title: "Live scenario demo — simhealthplan",
};

export default function ScenarioPage() {
  const plans = scenarioInputs.plans as unknown as Plan[];
  const archetypes = scenarioInputs.archetypes as unknown as Archetype[];
  const outsideOptionKey = scenarioInputs.outside_option_key;

  const baselineShares = aggregateWeightedShares(archetypes, plans, coefficients, outsideOptionKey);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-10 sm:px-8">
      <header className="flex flex-col gap-4">
        <nav className="flex items-center justify-between text-sm" style={{ color: "var(--text-secondary)" }}>
          <span className="font-semibold" style={{ color: "var(--text-primary)" }}>
            simhealthplan
          </span>
          <Link href="/" className="rounded-md border px-3 py-1.5" style={{ borderColor: "var(--border)" }}>
            ← Back to report
          </Link>
        </nav>
        <div className="flex flex-col gap-3">
          <h1 className="text-3xl font-semibold tracking-tight" style={{ color: "var(--text-primary)" }}>
            Live scenario demo
          </h1>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            &ldquo;What if Plan X cut premium $15 and dropped dental?&rdquo; -- pick a real 2025 Maricopa County plan
            and adjust its attributes. This recomputes the same calibrated multinomial-logit choice model against
            all {archetypes.length} synthetic archetypes, live, with pure math (no LLM calls, no external requests).
          </p>
        </div>
      </header>

      <ScenarioDemo plans={scenarioInputs.plans} baselineShares={baselineShares} />
    </div>
  );
}
