/**
 * "The verdict" -- the report's honesty-first headline: the calibrated
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
    ? { status: "good", label: "Beats no-change" }
    : { status: "critical", label: "Loses to no-change" };
}

/** Derives the directional-accuracy stat tile's badge from a real
 * comparison against both naive baselines, rather than a hardcoded literal.
 * Exported for the same pure-function-testability reason as `maeBadge`. */
export function accuracyBadge(logitAcc: number, noChangeAcc: number, trendAcc: number): { status: Status; label: string } {
  const beatsNoChange = logitAcc >= noChangeAcc;
  const beatsTrend = logitAcc >= trendAcc;
  if (beatsNoChange && beatsTrend) return { status: "good", label: "Beats both baselines" };
  if (beatsNoChange || beatsTrend) return { status: "warning", label: "Beats one baseline" };
  return { status: "critical", label: "Loses to both baselines" };
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
          The verdict
        </h2>
        <p className="max-w-3xl text-base" style={{ color: "var(--text-secondary)" }}>
          A rigorous <strong>negative result on magnitude</strong>, and a{" "}
          <strong>positive result on direction</strong>. The calibrated choice model does not out-predict a
          &ldquo;nothing changes&rdquo; guess on how much each plan&rsquo;s share moved — Maricopa County&rsquo;s
          2024→2025 market was unusually sticky — but it correctly calls the direction of that movement far more
          often than either naive baseline. Per the build spec, either outcome is a valid result; the deliverable is
          the evaluation methodology, not a flattering number.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatTile
          label="Weighted MAE (magnitude, lower is better)"
          value={pp(logitMae)}
          status={maeBadge(summary.beats_naive.logit)}
          caption="Size-weighted mean absolute error between predicted and actual 2025 share, in percentage points."
        >
          <MiniBarCompare
            maxValue={maeMax}
            rows={[
              { key: "logit", label: "Choice model", value: logitMae, valueLabel: pp(logitMae), emphasize: true },
              { key: "no_change", label: "Naive: no change", value: noChangeMae, valueLabel: pp(noChangeMae) },
              { key: "trend", label: "Naive: trend", value: trendMae, valueLabel: pp(trendMae) },
            ]}
          />
        </StatTile>

        <StatTile
          label="Directional accuracy (higher is better)"
          value={formatPercent(logitAcc)}
          status={accuracyBadge(logitAcc, noChangeAcc, trendAcc)}
          caption="Share of plans where the model correctly called the sign of the 2024→2025 share shift."
        >
          <MiniBarCompare
            maxValue={accMax}
            rows={[
              { key: "logit", label: "Choice model", value: logitAcc, valueLabel: formatPercent(logitAcc), emphasize: true },
              { key: "no_change", label: "Naive: no change", value: noChangeAcc, valueLabel: formatPercent(noChangeAcc) },
              { key: "trend", label: "Naive: trend", value: trendAcc, valueLabel: formatPercent(trendAcc) },
            ]}
          />
        </StatTile>

        <StatTile
          label="LLM-blended variant"
          value={blendedPending ? "Pending" : pp(blendedMae as number)}
          status={{ status: "muted", label: "Pending LLM pass" }}
          caption={
            blendedPending
              ? "Requires an OPENAI_API_KEY persona pass (`make personas`) to blend LLM persona reasoning into the logit baseline. Weighted MAE and directional accuracy will appear here once that run completes."
              : `Directional accuracy: ${formatPercent(blendedAcc)}.`
          }
        />
      </div>
    </section>
  );
}
