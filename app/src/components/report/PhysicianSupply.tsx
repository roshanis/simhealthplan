/**
 * "Physicians in the county" -- descriptive physician-supply context from
 * CMS's Doctors and Clinicians roster (see pipeline/parse/physicians.py).
 * Server component: static lists, no client JS.
 *
 * Honest-limitations contract: CMS publishes no physician<->plan-network
 * linkage, so this section is market context only -- it never feeds the
 * choice model, and the copy says so rather than implying otherwise.
 * Follows personas.json's graceful-absence pattern: renders a muted
 * placeholder until the pipeline has generated physicians.json.
 */

import { formatCount, formatPercent } from "@/lib/format";
import { StatTile } from "@/components/ui/StatTile";
import type { PhysiciansFile } from "@/lib/data/types";

const TOP_LIST_N = 10;

/** CMS ships names in ALL CAPS; title-case them for reading. */
function titleCase(value: string): string {
  return value.toLowerCase().replace(/(^|[\s(/-])([a-z])/g, (_, sep, ch) => sep + ch.toUpperCase());
}

function BarList({ rows, maxValue }: { rows: { label: string; value: number }[]; maxValue: number }) {
  return (
    <ul className="flex flex-col gap-2">
      {rows.map((row) => {
        const pct = maxValue > 0 ? Math.max(2, (row.value / maxValue) * 100) : 0;
        return (
          <li key={row.label} className="flex items-center gap-2">
            <span
              className="w-52 shrink-0 truncate text-xs"
              style={{ color: "var(--text-secondary)" }}
              title={row.label}
            >
              {row.label}
            </span>
            <div className="h-3 flex-1 overflow-hidden rounded" style={{ background: "var(--surface-2)" }}>
              <div className="h-full rounded" style={{ width: `${pct}%`, background: "var(--series-1)" }} />
            </div>
            <span
              className="w-14 shrink-0 text-right text-xs font-medium"
              style={{ color: "var(--text-secondary)", fontVariantNumeric: "tabular-nums" }}
            >
              {formatCount(row.value)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function PhysicianSupply({ physicians }: { physicians: PhysiciansFile }) {
  if (!physicians.available || !physicians.totals) {
    return (
      <div
        className="rounded-lg border px-3 py-2 text-xs"
        style={{ borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--text-secondary)" }}
      >
        Physician data is <strong>pending the ingest pass</strong> (<code>make ingest</code> then{" "}
        <code>make export</code>, which downloads CMS&rsquo;s Doctors and Clinicians roster). This section fills in
        automatically once it has run.
      </div>
    );
  }

  const totals = physicians.totals;
  const specialties = physicians.top_specialties
    .slice(0, TOP_LIST_N)
    .map((s) => ({ label: titleCase(s.specialty), value: s.clinicians }));
  const orgs = physicians.top_organizations
    .slice(0, TOP_LIST_N)
    .map((o) => ({ label: titleCase(o.org_name), value: o.clinicians }));
  const specialtyMax = specialties[0]?.value ?? 0;
  const orgMax = orgs[0]?.value ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatTile
          label="Clinicians"
          value={formatCount(totals.clinicians)}
          caption={`Unique clinicians with a Maricopa County practice address, across ${formatCount(totals.practice_locations)} practice locations.`}
        />
        <StatTile
          label="Medical groups"
          value={formatCount(totals.organizations)}
          caption="Distinct group practices (by CMS group PAC ID) with at least one clinician in the county."
        />
        <StatTile
          label="Offer telehealth"
          value={formatPercent(totals.telehealth_share)}
          caption="Share of clinicians who report offering telehealth at any of their practice locations."
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div
          className="flex flex-col gap-3 rounded-xl border p-4"
          style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
        >
          <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            Largest specialties
          </h3>
          <BarList rows={specialties} maxValue={specialtyMax} />
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            Top {specialties.length} of {formatCount(totals.specialties)} specialties, by clinician count.
          </p>
        </div>
        <div
          className="flex flex-col gap-3 rounded-xl border p-4"
          style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
        >
          <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            Largest medical groups
          </h3>
          <BarList rows={orgs} maxValue={orgMax} />
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            Top {orgs.length} of {formatCount(totals.organizations)} groups, by clinician count.
          </p>
        </div>
      </div>
    </div>
  );
}
