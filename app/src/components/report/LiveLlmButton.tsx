"use client";

/**
 * Optional "Generate live persona" button. Only rendered by the server page
 * when `ENABLE_LIVE_LLM === 'true'` at build/runtime (see `app/page.tsx`) --
 * in the default zero-env-var build this component never ships, and
 * `/api/persona-live` always 501s in that build regardless of whether this
 * button is even mounted (see that route's docstring).
 *
 * `page.tsx` renders `<LiveLlmButton />` with no props (out of this file's
 * ownership to change), so the archetype picker lives entirely in here:
 * `archetypesDisplay` is the same build-time-inlined static import
 * `lib/data/loaders.ts` already uses server-side (see that module's
 * docstring -- no request-time filesystem I/O either way), just consumed
 * from a client component instead of a server one.
 *
 * State machine: idle -> loading -> (success | error). "error" covers both
 * the gate 501s (flag off / no key -- surfaced via the `reason` field) and
 * real request failures (400/502/504 -- surfaced via the `error` field);
 * either way this button always shows the server's own explanation rather
 * than inventing one, and never fabricates a narrative on failure.
 */

import { useMemo, useState } from "react";

import { archetypesDisplay } from "@/lib/data/loaders";
import { formatAgeBand, humanizeToken } from "@/lib/format";

type LiveLlmState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; archetypeId: string; name: string; backstory: string }
  | { status: "error"; message: string };

function archetypeLabel(archetype: (typeof archetypesDisplay.archetypes)[number]): string {
  const income = archetype.demographics.income_tier ? `${humanizeToken(archetype.demographics.income_tier)} income` : "Mixed income";
  return `${formatAgeBand(archetype.demographics.age_band)} - ${income} - ${humanizeToken(archetype.segment)}`;
}

export function LiveLlmButton() {
  const archetypes = archetypesDisplay.archetypes;
  const [archetypeId, setArchetypeId] = useState<string>(archetypes[0]?.id ?? "");
  const [state, setState] = useState<LiveLlmState>({ status: "idle" });

  const options = useMemo(
    () => archetypes.map((archetype) => ({ id: archetype.id, label: archetypeLabel(archetype) })),
    [archetypes],
  );

  async function handleClick() {
    if (!archetypeId) return;
    setState({ status: "loading" });
    try {
      const response = await fetch("/api/persona-live", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ archetypeId }),
      });
      const body = await response.json().catch(() => ({}));

      if (response.ok && typeof body.name === "string" && typeof body.backstory === "string") {
        setState({ status: "success", archetypeId, name: body.name, backstory: body.backstory });
        return;
      }

      const reason =
        typeof body.reason === "string"
          ? body.reason
          : typeof body.error === "string"
            ? body.error
            : `HTTP ${response.status}`;
      setState({ status: "error", message: reason });
    } catch {
      setState({ status: "error", message: "Request failed." });
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
          Archetype
          <select
            value={archetypeId}
            onChange={(e) => setArchetypeId(e.target.value)}
            disabled={state.status === "loading"}
            className="rounded-md border px-2 py-1"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)", color: "var(--text-primary)" }}
          >
            {options.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={handleClick}
          disabled={state.status === "loading" || !archetypeId}
          className="rounded-md border px-3 py-1.5 text-xs font-medium"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
        >
          {state.status === "loading" ? "Requesting…" : "Generate live persona (experimental)"}
        </button>
      </div>

      {state.status === "error" && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Not available: {state.message}
        </p>
      )}

      {state.status === "success" && (
        <div
          className="flex flex-col gap-1 rounded-lg border px-3 py-2 text-xs"
          style={{ borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--text-secondary)" }}
        >
          <p className="font-semibold" style={{ color: "var(--text-primary)" }}>
            {state.name} <span style={{ color: "var(--text-muted)" }}>(live, not saved to personas.json)</span>
          </p>
          <p>{state.backstory}</p>
        </div>
      )}
    </div>
  );
}
