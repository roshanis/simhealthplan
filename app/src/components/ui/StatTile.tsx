import type { ReactNode } from "react";

import type { Status } from "@/components/ui/StatusBadge";
import { StatusBadge } from "@/components/ui/StatusBadge";

export interface StatTileProps {
  label: string;
  value: string;
  status?: { status: Status; label: string };
  caption?: string;
  children?: ReactNode;
}

/** Stat-tile contract (dataviz skill, `marks-and-anatomy.md`): label
 * (sentence case, no trailing colon), value (proportional figures, not
 * tabular-nums), optional status badge (icon+label, never color alone),
 * optional caption/children for a comparison mini-chart. */
export function StatTile({ label, value, status, caption, children }: StatTileProps) {
  return (
    <div
      className="flex flex-col gap-2 rounded-xl border p-4"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
          {label}
        </span>
        {status && <StatusBadge status={status.status} label={status.label} />}
      </div>
      <div className="text-3xl font-semibold" style={{ color: "var(--text-primary)", fontVariantNumeric: "proportional-nums" }}>
        {value}
      </div>
      {caption && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {caption}
        </p>
      )}
      {children}
    </div>
  );
}
