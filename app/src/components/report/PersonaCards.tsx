"use client";

/**
 * "Meet the market" -- browsable cards, one per synthetic archetype.
 * Filter row (segment, age band) sits above the grid per the dataviz
 * skill's interaction rules ("one row, above the charts, never per-card").
 * Cards paginate client-side (12 at a time) rather than rendering all 80 at
 * once, since this is a browsing UI, not a chart.
 */

import { useMemo, useState } from "react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import type { PersonaCardViewModel } from "@/lib/report/personas";

const PAGE_SIZE = 12;

export function PersonaCards({
  cards,
  personasAvailable,
  segments,
  ageBands,
}: {
  cards: PersonaCardViewModel[];
  personasAvailable: boolean;
  segments: string[];
  ageBands: string[];
}) {
  const [segmentFilter, setSegmentFilter] = useState<string>("all");
  const [ageFilter, setAgeFilter] = useState<string>("all");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const filtered = useMemo(() => {
    return cards.filter((card) => {
      if (segmentFilter !== "all" && card.segmentLabel !== segmentFilter) return false;
      if (ageFilter !== "all" && card.ageBandLabel !== ageFilter) return false;
      return true;
    });
  }, [cards, segmentFilter, ageFilter]);

  const visible = filtered.slice(0, visibleCount);

  return (
    <div className="flex flex-col gap-4">
      {!personasAvailable && (
        <div
          className="rounded-lg border px-3 py-2 text-xs"
          style={{ borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--text-secondary)" }}
        >
          Persona backstories are <strong>pending the LLM pass</strong> (<code>make personas</code>, requires an{" "}
          <code>OPENAI_API_KEY</code>). Cards below show archetype demographics and Year-1 plan-choice data only;
          names are deterministic placeholders until backstories exist.
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <FilterSelect label="Attitude segment" value={segmentFilter} onChange={setSegmentFilter} options={segments} />
        <FilterSelect label="Age band" value={ageFilter} onChange={setAgeFilter} options={ageBands} />
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {filtered.length} of {cards.length} archetypes
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visible.map((card) => (
          <PersonaCard key={card.id} card={card} />
        ))}
      </div>

      {visibleCount < filtered.length && (
        <button
          type="button"
          onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}
          className="self-center rounded-md border px-4 py-2 text-sm font-medium"
          style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
        >
          Show more ({filtered.length - visibleCount} remaining)
        </button>
      )}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border px-2 py-1"
        style={{ borderColor: "var(--border)", background: "var(--surface-1)", color: "var(--text-primary)" }}
      >
        <option value="all">All</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </label>
  );
}

function PersonaCard({ card }: { card: PersonaCardViewModel }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="flex flex-col gap-3 rounded-xl border p-4"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
          {card.name}
        </h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {card.ageBandLabel} · {card.incomeTierLabel} income · {card.raceEthLabel}
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Badge>{card.segmentLabel}</Badge>
        {card.dualEligibleProxy && <Badge>Dual-eligible proxy</Badge>}
        <Badge>{card.weightLabel}</Badge>
        <Badge>{card.shareOfPopulationLabel} of population</Badge>
      </div>

      {card.traits.length > 0 && (
        <ul className="flex list-disc flex-col gap-1 pl-4 text-xs" style={{ color: "var(--text-secondary)" }}>
          {card.traits.slice(0, expanded ? undefined : 2).map((trait) => (
            <li key={trait}>{trait}</li>
          ))}
        </ul>
      )}

      {expanded && (
        <div className="flex flex-col gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
          {card.hasBackstory ? (
            <>
              <p>{card.backstory}</p>
              {card.rationale && (
                <p style={{ color: "var(--text-muted)" }}>
                  <strong>Choice rationale:</strong> {card.rationale}
                </p>
              )}
            </>
          ) : (
            <p style={{ color: "var(--text-muted)" }}>
              <StatusBadge status="muted" label="Backstory pending" /> This persona&rsquo;s narrative backstory will
              appear here once the LLM persona pass runs.
            </p>
          )}
          {card.topPlans.length > 0 && (
            <div>
              <strong style={{ color: "var(--text-primary)" }}>Historically favored plans:</strong>
              <ul className="list-disc pl-4">
                {card.topPlans.map((p) => (
                  <li key={p.planKey}>{p.label}</li>
                ))}
              </ul>
            </div>
          )}
          <p style={{ color: "var(--text-muted)" }}>
            {card.outsideShareLabel} prior probability of no MA plan / traditional Medicare.
          </p>
        </div>
      )}

      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        className="self-start text-xs font-medium underline"
        style={{ color: "var(--text-primary)" }}
      >
        {expanded ? "Show less" : "Show more"}
      </button>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[11px]"
      style={{ background: "var(--surface-2)", color: "var(--text-secondary)" }}
    >
      {children}
    </span>
  );
}
