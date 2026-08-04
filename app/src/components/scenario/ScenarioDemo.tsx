"use client";

/**
 * Interactive counterfactual controls: pick a 2025 plan, adjust premium
 * delta / MOOP delta / star delta / dental / vision / hearing / OTC, POST to
 * `/api/scenario`, and render before/after shares for the changed plan +
 * top movers + Monte Carlo p10/p90 bands. Pure recompute, no LLM calls --
 * the round trip is the existing TS engine running against
 * `scenario_inputs.json`.
 */

import { useMemo, useState } from "react";

import { ShareBand } from "@/components/scenario/ShareBand";
import { formatMoney, formatMoneyDelta, formatPercent, formatSignedPP, planLabel } from "@/lib/format";
import type { ScenarioPlanRecord } from "@/lib/data/types";
import type { ScenarioResult } from "@/lib/scenario/runScenario";

function ppLabel(value: number): string {
  return formatSignedPP(value, 3);
}

/**
 * One-click scenario presets. Each references a REAL `plan_key` present in
 * `scenario_inputs.json` (verified against the exported data, not
 * invented) and overrides only the fields it cares about -- every other
 * control resets to that plan's own baseline via `selectPlan`, exactly as
 * if a person had picked the plan from the dropdown themselves.
 *
 * `premiumCutDropDental` is the build spec's canonical example scenario
 * ("what if Plan X cut premium $15 and dropped dental?"), applied to
 * H0321-002 (UHC Dual Complete AZ-S001), the market's single largest plan
 * by 2024 enrollment (40,658 -- see `scenario_inputs.json`).
 */
interface ScenarioPreset {
  id: string;
  title: string;
  description: string;
  planKey: string;
  premiumDelta?: number;
  starDelta?: number;
  dental?: boolean;
  vision?: boolean;
  hearing?: boolean;
  otc?: boolean;
}

const SCENARIO_PRESETS: ScenarioPreset[] = [
  {
    id: "premium-cut-drop-dental",
    title: "Cut premium $15, drop dental",
    description: "UHC Dual Complete AZ-S001 -- the market's largest plan (build spec's canonical example).",
    planKey: "H0321-002",
    premiumDelta: -15,
    dental: false,
  },
  {
    id: "add-dental",
    title: "Add comprehensive dental",
    description: "AZ Blue Best Life Classic -- a large plan (21,134 enrolled) that currently lacks the benefit.",
    planKey: "H0302-006",
    dental: true,
  },
  {
    id: "premium-hike",
    title: "Raise premium $20",
    description: "Humana Gold Plus H0028-074 -- currently $0/mo, third-largest plan in the market.",
    planKey: "H0028-074",
    premiumDelta: 20,
  },
];

export function ScenarioDemo({
  plans,
  baselineShares,
}: {
  plans: ScenarioPlanRecord[];
  baselineShares: Record<string, number>;
}) {
  const sortedPlans = useMemo(() => [...plans].sort((a, b) => b.enrollment - a.enrollment), [plans]);
  // Defensive: only offer presets whose plan_key actually exists in the
  // exported `scenario_inputs.json` roster passed in as `plans`, so a
  // future data refresh that drops/renames a plan can't leave a dead
  // preset button in the UI.
  const availablePresets = useMemo(
    () => SCENARIO_PRESETS.filter((preset) => plans.some((p) => p.plan_key === preset.planKey)),
    [plans],
  );
  const [planKey, setPlanKey] = useState(sortedPlans[0]?.plan_key ?? "");
  const plan = plans.find((p) => p.plan_key === planKey) ?? sortedPlans[0];

  const [premiumDelta, setPremiumDelta] = useState(0);
  const [moopDelta, setMoopDelta] = useState(0);
  const [starDelta, setStarDelta] = useState(0);
  const [dental, setDental] = useState(plan?.has_comprehensive_dental ?? true);
  const [vision, setVision] = useState(plan?.has_vision ?? true);
  const [hearing, setHearing] = useState(plan?.has_hearing_aids ?? true);
  const [otc, setOtc] = useState(plan?.has_otc_or_flex ?? true);

  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  function selectPlan(key: string) {
    setPlanKey(key);
    const next = plans.find((p) => p.plan_key === key);
    setDental(next?.has_comprehensive_dental ?? true);
    setVision(next?.has_vision ?? true);
    setHearing(next?.has_hearing_aids ?? true);
    setOtc(next?.has_otc_or_flex ?? true);
    setPremiumDelta(0);
    setMoopDelta(0);
    setStarDelta(0);
    setResult(null);
  }

  /** Applies a preset through the exact same state setters manual entry
   * uses -- `selectPlan` first (so every control resets to that plan's own
   * baseline, same as clicking it in the dropdown), then the preset's
   * explicit overrides. No separate code path to `/api/scenario`; the
   * "Run scenario" button and its existing validation (`changes.length
   * === 0` disables it) still gate the request exactly as they do for a
   * fully manual selection. */
  function applyPreset(preset: ScenarioPreset) {
    if (!plans.some((p) => p.plan_key === preset.planKey)) return;
    selectPlan(preset.planKey);
    if (preset.premiumDelta !== undefined) setPremiumDelta(preset.premiumDelta);
    if (preset.starDelta !== undefined) setStarDelta(preset.starDelta);
    if (preset.dental !== undefined) setDental(preset.dental);
    if (preset.vision !== undefined) setVision(preset.vision);
    if (preset.hearing !== undefined) setHearing(preset.hearing);
    if (preset.otc !== undefined) setOtc(preset.otc);
  }

  const changes = useMemo(() => {
    if (!plan) return [];
    const list: Record<string, unknown>[] = [];
    if (premiumDelta !== 0) list.push({ plan_key: plan.plan_key, field: "premium_total", delta: premiumDelta });
    if (moopDelta !== 0) list.push({ plan_key: plan.plan_key, field: "moop_inn", delta: moopDelta });
    if (starDelta !== 0) list.push({ plan_key: plan.plan_key, field: "star_rating", delta: starDelta });
    if (dental !== plan.has_comprehensive_dental) list.push({ plan_key: plan.plan_key, field: "has_comprehensive_dental", set: dental });
    if (vision !== plan.has_vision) list.push({ plan_key: plan.plan_key, field: "has_vision", set: vision });
    if (hearing !== plan.has_hearing_aids) list.push({ plan_key: plan.plan_key, field: "has_hearing_aids", set: hearing });
    if (otc !== plan.has_otc_or_flex) list.push({ plan_key: plan.plan_key, field: "has_otc_or_flex", set: otc });
    return list;
  }, [plan, premiumDelta, moopDelta, starDelta, dental, vision, hearing, otc]);

  async function runScenario() {
    if (changes.length === 0) return;
    setStatus("loading");
    setError(null);
    const start = performance.now();
    try {
      const response = await fetch("/api/scenario", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ changes }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.error ?? `Request failed (HTTP ${response.status})`);
        setStatus("error");
        return;
      }
      setResult(body as ScenarioResult);
      setElapsedMs(performance.now() - start);
      setStatus("idle");
    } catch {
      setError("Request failed. Check your connection and try again.");
      setStatus("error");
    }
  }

  if (!plan) return null;

  return (
    <div className="flex flex-col gap-8 lg:flex-row">
      <div className="flex w-full flex-col gap-5 lg:max-w-sm">
        {availablePresets.length > 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Try a preset
            </span>
            <div className="flex flex-col gap-2">
              {availablePresets.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => applyPreset(preset)}
                  className="flex flex-col items-start gap-0.5 rounded-md border px-3 py-2 text-left text-sm"
                  style={{ borderColor: "var(--border)", background: "var(--surface-1)", color: "var(--text-primary)" }}
                >
                  <span className="font-medium">{preset.title}</span>
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {preset.description}
                  </span>
                </button>
              ))}
            </div>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              Populates the controls below -- still requires &ldquo;Run scenario&rdquo; to recompute.
            </p>
          </div>
        )}

        <label className="flex flex-col gap-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          2025 plan
          <select
            value={planKey}
            onChange={(e) => selectPlan(e.target.value)}
            className="rounded-md border px-2 py-2"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)", color: "var(--text-primary)" }}
          >
            {sortedPlans.map((p) => (
              <option key={p.plan_key} value={p.plan_key}>
                {planLabel(p.org_name, p.plan_name)} ({p.enrollment.toLocaleString("en-US")} enrolled)
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          Premium change: <strong style={{ color: "var(--text-primary)" }}>{formatMoneyDelta(premiumDelta, 0)}/mo</strong>
          <input
            type="range"
            min={-100}
            max={50}
            step={5}
            value={premiumDelta}
            onChange={(e) => setPremiumDelta(Number(e.target.value))}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          Out-of-pocket maximum change:{" "}
          <strong style={{ color: "var(--text-primary)" }}>{formatMoneyDelta(moopDelta, 0)}/yr</strong>
          <input
            type="range"
            min={-3000}
            max={3000}
            step={250}
            value={moopDelta}
            onChange={(e) => setMoopDelta(Number(e.target.value))}
          />
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            The most a member can pay out of pocket in a year (MOOP). This plan&rsquo;s current cap:{" "}
            {formatMoney(plan.moop_inn, 0)}.
          </span>
        </label>

        <label className="flex flex-col gap-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          Star rating change: <strong style={{ color: "var(--text-primary)" }}>{starDelta > 0 ? "+" : ""}{starDelta.toFixed(1)}</strong>
          <input
            type="range"
            min={-2}
            max={2}
            step={0.5}
            value={starDelta}
            onChange={(e) => setStarDelta(Number(e.target.value))}
          />
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            Note: this pilot&rsquo;s fitted model has b_star = 0 -- star changes have no predicted effect (see
            Methodology).
          </span>
        </label>

        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Benefits
          </legend>
          <Toggle label="Comprehensive dental" checked={dental} onChange={setDental} />
          <Toggle label="Vision" checked={vision} onChange={setVision} />
          <Toggle label="Hearing aids" checked={hearing} onChange={setHearing} />
          <Toggle label="OTC / flex allowance" checked={otc} onChange={setOtc} />
        </fieldset>

        <button
          type="button"
          onClick={runScenario}
          disabled={changes.length === 0 || status === "loading"}
          className="rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-40"
          style={{ background: "var(--text-primary)", color: "var(--surface-1)" }}
        >
          {status === "loading" ? "Recomputing…" : "Run scenario"}
        </button>
        {changes.length === 0 && (
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            Adjust a control above to enable recompute.
          </p>
        )}
        {error && (
          <p className="text-xs" style={{ color: "var(--text-primary)" }}>
            <span aria-hidden="true" style={{ color: "var(--status-critical)" }}>
              ⚠{" "}
            </span>
            {error}
          </p>
        )}
        {elapsedMs !== null && result && (
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            Recomputed in {Math.round(elapsedMs)}ms.
          </p>
        )}
      </div>

      <div className="flex-1">
        {!result ? (
          <div
            className="flex h-full items-center justify-center rounded-xl border p-8 text-center text-sm"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            Baseline share for {planLabel(plan.org_name, plan.plan_name)}: {formatPercent(baselineShares[plan.plan_key] ?? 0, 3)}
            . Adjust the controls and run a scenario to see the effect.
          </div>
        ) : (
          <ScenarioResults result={result} plans={plans} />
        )}
      </div>
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-primary)" }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function ScenarioResults({ result, plans }: { result: ScenarioResult; plans: ScenarioPlanRecord[] }) {
  const planByKey = new Map(plans.map((p) => [p.plan_key, p]));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="mb-2 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
          Affected plan{result.affected.length > 1 ? "s" : ""}
        </h2>
        <MoversTable moves={result.affected} planByKey={planByKey} bounds={result.scenario.bounds} />
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
          Top movers elsewhere in the market
        </h2>
        <MoversTable moves={result.top_movers} planByKey={planByKey} bounds={result.scenario.bounds} />
      </div>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        Band shows the Monte Carlo p10–p90 range (200 seeded draws, ±10% coefficient jitter) around the scenario
        point estimate; gray tick marks the baseline share.
      </p>
    </div>
  );
}

function MoversTable({
  moves,
  planByKey,
  bounds,
}: {
  moves: ScenarioResult["affected"];
  planByKey: Map<string, ScenarioPlanRecord>;
  bounds: ScenarioResult["scenario"]["bounds"];
}) {
  if (moves.length === 0) {
    return (
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        No movement.
      </p>
    );
  }

  return (
    <div className="scroll-container rounded-xl border" style={{ borderColor: "var(--border)" }}>
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            <th className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
              Plan
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              Before
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              After
            </th>
            <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
              Δ
            </th>
            <th className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
              p10–p90 band
            </th>
          </tr>
        </thead>
        <tbody style={{ fontVariantNumeric: "tabular-nums" }}>
          {moves.map((m) => {
            const plan = planByKey.get(m.plan_key);
            const band = bounds[m.plan_key];
            return (
              <tr key={m.plan_key} style={{ borderBottom: "1px solid var(--gridline)" }}>
                <td className="px-3 py-2" style={{ color: "var(--text-primary)" }}>
                  {plan ? planLabel(plan.org_name, plan.plan_name) : m.plan_key}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>
                  {formatPercent(m.baseline_share, 3)}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                  {formatPercent(m.scenario_share, 3)}
                </td>
                <td className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-primary)" }}>
                  <span aria-hidden="true" style={{ color: "var(--text-secondary)" }}>
                    {m.delta_pp >= 0 ? "▲" : "▼"}{" "}
                  </span>
                  {ppLabel(m.delta_pp)}
                </td>
                <td className="px-3 py-2">
                  {band && (
                    <ShareBand baseline={m.baseline_share} scenario={m.scenario_share} p10={band.p10} p90={band.p90} />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
