"use client";

/**
 * "The world the personas live in" -- a sortable 2024/2025 plan-roster
 * table plus headline market facts. Client component for the year toggle +
 * column sort; data itself comes from the server-rendered page's
 * `market.json` import (passed down as props, not fetched).
 */

import { useMemo, useState } from "react";

import { formatMoney, formatStars } from "@/lib/format";
import type { MarketFact } from "@/lib/report/marketFacts";
import type { MarketPlan } from "@/lib/data/types";

type SortKey = "org_name" | "plan_name" | "plan_type" | "premium_total" | "moop_inn" | "star_rating" | "enrollment";

const COLUMNS: { key: SortKey; label: string; align: "left" | "right" }[] = [
  { key: "org_name", label: "Org", align: "left" },
  { key: "plan_name", label: "Plan", align: "left" },
  { key: "plan_type", label: "Type", align: "left" },
  { key: "premium_total", label: "Premium", align: "right" },
  { key: "moop_inn", label: "MOOP", align: "right" },
  { key: "star_rating", label: "Stars", align: "right" },
  { key: "enrollment", label: "Enrollment", align: "right" },
];

function FlagDot({ on, label }: { on: boolean; label: string }) {
  return (
    <span
      title={`${label}: ${on ? "included" : "not included"}`}
      aria-label={`${label}: ${on ? "included" : "not included"}`}
      className="inline-block h-2.5 w-2.5 rounded-full"
      style={{ background: on ? "var(--series-1)" : "var(--surface-2)", border: on ? "none" : "1px solid var(--border)" }}
    />
  );
}

export function MarketSnapshot({
  plansByYear,
  facts,
  years,
}: {
  plansByYear: Record<string, MarketPlan[]>;
  facts: MarketFact[];
  years: string[];
}) {
  const [year, setYear] = useState(years[years.length - 1] ?? years[0]);
  const [sortKey, setSortKey] = useState<SortKey>("enrollment");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const plans = useMemo(() => plansByYear[year] ?? [], [plansByYear, year]);

  const sorted = useMemo(() => {
    const copy = [...plans];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const cmp = typeof av === "string" && typeof bv === "string" ? av.localeCompare(bv) : Number(av) - Number(bv);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [plans, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {facts.map((fact) => (
          <li
            key={fact.id}
            className="rounded-lg border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)", color: "var(--text-secondary)" }}
          >
            {fact.text}
          </li>
        ))}
      </ul>

      <div className="flex items-center gap-2">
        {years.map((y) => (
          <button
            key={y}
            type="button"
            onClick={() => setYear(y)}
            aria-pressed={year === y}
            className="rounded-md border px-3 py-1.5 text-sm font-medium"
            style={{
              borderColor: "var(--border)",
              background: year === y ? "var(--text-primary)" : "var(--surface-1)",
              color: year === y ? "var(--surface-1)" : "var(--text-secondary)",
            }}
          >
            {y}
          </button>
        ))}
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {plans.length} plans
        </span>
      </div>

      <div className="scroll-container rounded-xl border" style={{ borderColor: "var(--border)" }}>
        <table className="w-full min-w-[860px] border-collapse text-sm">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={`px-3 py-2 font-medium ${col.align === "right" ? "text-right" : "text-left"}`}
                  style={{ color: "var(--text-secondary)" }}
                  aria-sort={sortKey === col.key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                >
                  <button
                    type="button"
                    onClick={() => toggleSort(col.key)}
                    className="inline-flex items-center gap-1"
                    aria-label={`Sort by ${col.label}${
                      sortKey === col.key ? `, currently ${sortDir === "asc" ? "ascending" : "descending"}` : ""
                    }`}
                  >
                    {col.label}
                    {sortKey === col.key && <span aria-hidden="true">{sortDir === "asc" ? "▲" : "▼"}</span>}
                  </button>
                </th>
              ))}
              <th className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
                Benefits
              </th>
            </tr>
          </thead>
          <tbody style={{ fontVariantNumeric: "tabular-nums" }}>
            {sorted.map((plan) => (
              <tr key={plan.plan_key} style={{ borderBottom: "1px solid var(--gridline)" }}>
                <td className="px-3 py-2" style={{ color: "var(--text-primary)" }}>
                  {plan.org_name}
                </td>
                <td className="px-3 py-2" style={{ color: "var(--text-primary)" }}>
                  {plan.plan_name}
                </td>
                <td className="px-3 py-2" style={{ color: "var(--text-secondary)" }}>
                  {plan.plan_type}
                  {plan.snp_type !== "Not Applicable" ? ` · ${plan.snp_type}` : ""}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                  {formatMoney(plan.premium_total)}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                  {formatMoney(plan.moop_inn, 0)}
                  {plan.imputed_moop && (
                    <span title="Imputed MOOP" aria-label="Imputed MOOP" style={{ color: "var(--text-muted)" }}>
                      {" "}
                      *
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                  {formatStars(plan.star_rating)}
                  {plan.imputed_star && (
                    <span title="Imputed star rating" aria-label="Imputed star rating" style={{ color: "var(--text-muted)" }}>
                      {" "}
                      *
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                  {plan.enrollment.toLocaleString("en-US")}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    <FlagDot on={plan.has_comprehensive_dental} label="Dental" />
                    <FlagDot on={plan.has_vision} label="Vision" />
                    <FlagDot on={plan.has_hearing_aids} label="Hearing" />
                    <FlagDot on={plan.has_otc_or_flex} label="OTC/flex" />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        Dots left to right: dental, vision, hearing, OTC/flex (filled = included). * marks an imputed value (see
        Methodology).
      </p>
    </div>
  );
}
