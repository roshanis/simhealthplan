"use client";

/**
 * Hypothetical provider-network designer: check real Maricopa medical
 * groups in and out of a draft network, set a planned enrollment, and see
 * per-specialty clinician counts scored against the configurable adequacy
 * targets in network_standards.json (see lib/network/adequacy.ts for what
 * is and isn't computed -- the honest-limitations copy below mirrors it).
 * Pure client-side arithmetic over the build-time artifact; no API calls.
 */

import { useMemo, useState } from "react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { assessNetwork, totalNetworkClinicians } from "@/lib/network/adequacy";
import { formatCount, formatPercent } from "@/lib/format";
import type { NetworkInputsFile, NetworkStandardsFile } from "@/lib/data/types";

const DEFAULT_ENROLLMENT = 10_000;
const DEFAULT_PRESELECTED = 5;
const ORG_PAGE_SIZE = 25;

/** CMS ships names in ALL CAPS; title-case them for reading. */
function titleCase(value: string): string {
  return value.toLowerCase().replace(/(^|[\s(/-])([a-z])/g, (_, sep, ch) => sep + ch.toUpperCase());
}

export function NetworkDesigner({
  inputs,
  standards,
}: {
  inputs: NetworkInputsFile;
  standards: NetworkStandardsFile;
}) {
  const orgs = inputs.organizations;
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(orgs.slice(0, DEFAULT_PRESELECTED).map((o) => o.org_pac_id)),
  );
  const [enrollment, setEnrollment] = useState(DEFAULT_ENROLLMENT);
  const [filter, setFilter] = useState("");
  const [visibleCount, setVisibleCount] = useState(ORG_PAGE_SIZE);

  const filteredOrgs = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return orgs;
    return orgs.filter((o) => o.org_name.toLowerCase().includes(needle));
  }, [orgs, filter]);

  const selectedOrgs = useMemo(() => orgs.filter((o) => selected.has(o.org_pac_id)), [orgs, selected]);

  const assessments = useMemo(
    () => assessNetwork(selectedOrgs, standards.specialties, inputs.zctas.length, enrollment),
    [selectedOrgs, standards.specialties, inputs.zctas.length, enrollment],
  );

  function toggleOrg(pacId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(pacId)) {
        next.delete(pacId);
      } else {
        next.add(pacId);
      }
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-8 lg:flex-row">
      <div className="flex w-full flex-col gap-4 lg:max-w-sm">
        <label className="flex flex-col gap-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          Planned plan enrollment:{" "}
          <strong style={{ color: "var(--text-primary)" }}>{formatCount(enrollment)} members</strong>
          <input
            type="range"
            min={1000}
            max={100_000}
            step={1000}
            value={enrollment}
            onChange={(e) => setEnrollment(Number(e.target.value))}
          />
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            Required provider counts scale with enrollment (target ratio × members ÷ 1,000).
          </span>
        </label>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Medical groups ({selected.size} in network)
            </span>
            <button
              type="button"
              onClick={() => setSelected(new Set())}
              className="text-xs underline"
              style={{ color: "var(--text-secondary)" }}
            >
              Clear all
            </button>
          </div>
          <input
            type="search"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setVisibleCount(ORG_PAGE_SIZE);
            }}
            placeholder="Search groups…"
            className="rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)", color: "var(--text-primary)" }}
          />
          <ul
            className="flex max-h-96 flex-col gap-1 overflow-y-auto rounded-xl border p-2"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
          >
            {filteredOrgs.slice(0, visibleCount).map((org) => (
              <li key={org.org_pac_id}>
                <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm">
                  <input
                    type="checkbox"
                    checked={selected.has(org.org_pac_id)}
                    onChange={() => toggleOrg(org.org_pac_id)}
                  />
                  <span className="flex-1 truncate" style={{ color: "var(--text-primary)" }} title={titleCase(org.org_name)}>
                    {titleCase(org.org_name)}
                  </span>
                  <span className="shrink-0 text-xs" style={{ color: "var(--text-muted)" }}>
                    {formatCount(org.clinicians)}
                  </span>
                </label>
              </li>
            ))}
            {filteredOrgs.length === 0 && (
              <li className="px-1 py-2 text-xs" style={{ color: "var(--text-muted)" }}>
                No groups match &ldquo;{filter}&rdquo;.
              </li>
            )}
          </ul>
          {visibleCount < filteredOrgs.length && (
            <button
              type="button"
              onClick={() => setVisibleCount((c) => c + ORG_PAGE_SIZE)}
              className="self-start text-xs underline"
              style={{ color: "var(--text-secondary)" }}
            >
              Show more ({filteredOrgs.length - visibleCount} remaining)
            </button>
          )}
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            The {formatCount(orgs.length)} largest groups in the county, by clinician count. Numbers are clinicians
            per group; a clinician credentialed with several groups counts in each.
          </p>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-4">
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          Your draft network: <strong style={{ color: "var(--text-primary)" }}>{selected.size}</strong> groups,{" "}
          <strong style={{ color: "var(--text-primary)" }}>{formatCount(totalNetworkClinicians(selectedOrgs))}</strong>{" "}
          clinicians.
        </p>

        <div className="scroll-container rounded-xl border" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <table className="w-full min-w-[680px] border-collapse text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <th className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
                  Specialty
                </th>
                <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
                  In network
                </th>
                <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
                  Per 1,000 members
                </th>
                <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
                  Required
                </th>
                <th className="px-3 py-2 text-right font-medium" style={{ color: "var(--text-secondary)" }}>
                  ZIP coverage
                </th>
                <th className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>
                  Status
                </th>
              </tr>
            </thead>
            <tbody style={{ fontVariantNumeric: "tabular-nums" }}>
              {assessments.map((a) => (
                <tr key={a.key} style={{ borderBottom: "1px solid var(--gridline)" }}>
                  <td className="px-3 py-2" style={{ color: "var(--text-primary)" }}>
                    {a.label}
                  </td>
                  <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                    {formatCount(a.clinicians)}
                  </td>
                  <td className="px-3 py-2 text-right" style={{ color: "var(--text-primary)" }}>
                    {a.achievedRatioPer1000.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>
                    {a.requiredClinicians === null ? "—" : formatCount(a.requiredClinicians)}
                  </td>
                  <td className="px-3 py-2 text-right" style={{ color: "var(--text-secondary)" }}>
                    {formatPercent(a.zctaCoverage)}
                  </td>
                  <td className="px-3 py-2">
                    {a.meetsTarget === null ? (
                      <StatusBadge status="muted" label="No target set" />
                    ) : a.meetsTarget ? (
                      <StatusBadge status="good" label="Meets target" />
                    ) : (
                      <StatusBadge
                        status="critical"
                        label={`Short by ${formatCount((a.requiredClinicians ?? 0) - a.clinicians)}`}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div
          className="rounded-lg border px-3 py-2 text-xs"
          style={{ borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--text-secondary)" }}
        >
          <strong style={{ color: "var(--text-primary)" }}>What this is (and isn&rsquo;t).</strong>{" "}A sketchpad over
          CMS&rsquo;s public clinician roster — real groups, real clinician counts. It is not a compliance check:
          targets marked &ldquo;No target set&rdquo; have no verified CMS ratio loaded (edit{" "}
          <code>network_standards.json</code>{" "}with your county&rsquo;s official HSD Reference Table values); ZIP
          coverage is presence-based, not CMS&rsquo;s drive-time standard; and actual network contracts are
          negotiated with each group — appearing in the roster doesn&rsquo;t mean a group would join your network.
        </div>
      </div>
    </div>
  );
}
