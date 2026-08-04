/**
 * "What we found" -- the report's honesty-first headline: the calibrated
 * choice model loses to the no-change naive baseline on magnitude (weighted
 * MAE) but beats both baselines on direction. Never hides `beats_naive.logit
 * === false` behind vague language; states both numbers side by side and
 * lets the reader see the tradeoff directly.
 */

import { MiniBarCompare } from "@/components/ui/MiniBarCompare";
import { StatTile } from "@/components/ui/StatTile";
import { formatAbsPP, formatPercent } from "@/lib/format";
import type { BacktestSummary } from "@/lib/data/types";
import type { Status } from "@/components/ui/StatusBadge";

const pp = formatAbsPP;

/** Derives the MAE stat tile's badge from `summary.beats_naive.logit`
 * directly, rather than a hardcoded literal, so a future backtest rerun
 * that flips the verdict can't silently desync this copy from the data.
 * Exported (rather than kept module-private) so it's unit-testable as a
 * pure function without rendering -- see
 * `tests/components/verdict-derivation.test.ts`. */
export function maeBadge(beatsNaiveLogit: boolean | null): { status: Status; label: string } {
  if (beatsNaiveLogit === null || beatsNaiveLogit === undefined) {
    return { status: "muted", label: "Pending" };
  }
  return beatsNaiveLogit
    ? { status: "good", label: "Better than baseline" }
    : { status: "critical", label: "Worse than baseline" };
}

/** Derives the directional-accuracy stat tile's badge from a real
 * comparison against both naive baselines, rather than a hardcoded literal.
 * Exported for the same pure-function-testability reason as `maeBadge`. */
export function accuracyBadge(logitAcc: number, noChangeAcc: number, trendAcc: number): { status: Status; label: string } {
  const beatsNoChange = logitAcc >= noChangeAcc;
  const beatsTrend = logitAcc >= trendAcc;
  if (beatsNoChange && beatsTrend) return { status: "good", label: "Better than both baselines" };
  if (beatsNoChange || beatsTrend) return { status: "warning", label: "Better than one baseline" };
  return { status: "critical", label: "Worse than both baselines" };
}

export function VerdictSection({ summary }: { summary: BacktestSummary }) {
  const logitMae = summary.weighted_mae.logit ?? 0;
  const noChangeMae = summary.weighted_mae.no_change ?? 0;
  const trendMae = summary.weighted_mae.trend ?? 0;
  const maeMax = Math.max(logitMae, noChangeMae, trendMae);

  const logitAcc = summary.directional_accuracy.logit ?? 0;
  const noChangeAcc = summary.directional_accuracy.no_change ?? 0;
  const trendAcc = summary.directional_accuracy.trend ?? 0;
  const accMax = Math.max(logitAcc, noChangeAcc, trendAcc);

  const blendedMae = summary.weighted_mae.blended;
  const blendedAcc = summary.directional_accuracy.blended;
  const blendedPending = blendedMae === null || blendedMae === undefined;

  return (
    <section aria-labelledby="verdict-heading" className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <h2 id="verdict-heading" className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
          What we found
        </h2>
        <p className="max-w-3xl text-base" style={{ color: "var(--text-secondary)" }}>
          The model was good at predicting <strong>which way</strong>{" "}each plan&rsquo;s enrollment would move — better
          than two simple baselines (&ldquo;assume nothing changes&rdquo; and &ldquo;extend last year&rsquo;s
          trend&rdquo;). It was not good at predicting <strong>by how much</strong>: on the size of the shifts,
          assuming nothing changes was more accurate. Few people switch plans year to year, which makes &ldquo;no
          change&rdquo; a hard guess to beat. Both results are shown below.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatTile
          label="Size of shift — average error (lower is better)"
          value={pp(logitMae)}
          status={maeBadge(summary.beats_naive.logit)}
          caption="How far off the predicted 2025 market shares were, on average (enrollment-weighted mean absolute error, in percentage points)."
        >
          <MiniBarCompare
            maxValue={maeMax}
            rows={[
              { key: "logit", label: "Choice model", value: logitMae, valueLabel: pp(logitMae), emphasize: true },
              { key: "no_change", label: "Baseline: no change", value: noChangeMae, valueLabel: pp(noChangeMae) },
              { key: "trend", label: "Baseline: trend", value: trendMae, valueLabel: pp(trendMae) },
            ]}
          />
        </StatTile>

        <StatTile
          label="Direction of shift — called correctly (higher is better)"
          value={formatPercent(logitAcc)}
          status={accuracyBadge(logitAcc, noChangeAcc, trendAcc)}
          caption="Share of plans where the model correctly predicted whether enrollment would grow or shrink from 2024 to 2025."
        >
          <MiniBarCompare
            maxValue={accMax}
            rows={[
              { key: "logit", label: "Choice model", value: logitAcc, valueLabel: formatPercent(logitAcc), emphasize: true },
              { key: "no_change", label: "Baseline: no change", value: noChangeAcc, valueLabel: formatPercent(noChangeAcc) },
              { key: "trend", label: "Baseline: trend", value: trendAcc, valueLabel: formatPercent(trendAcc) },
            ]}
          />
        </StatTile>

        <StatTile
          label="With LLM personas blended in"
          value={blendedPending ? "Pending" : pp(blendedMae as number)}
          status={blendedPending ? { status: "muted", label: "Not yet run" } : maeBadge(summary.beats_naive.blended)}
          caption={
            blendedPending
              ? "A variant that adds LLM persona reasoning to the model. Results appear here once that pass has been run."
              : `Average error for a variant that adds LLM persona reasoning to the model. Direction called correctly: ${formatPercent(blendedAcc ?? 0)}.`
          }
        />
      </div>
    </section>
  );
}
