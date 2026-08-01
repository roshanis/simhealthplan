/**
 * Status badge: icon + label, never color alone (dataviz skill's status-
 * palette rule -- warning/serious sit below 3:1 contrast on the light
 * surface by design; the icon+label pairing is the documented mitigation).
 * Status tokens are reserved and never reused as a categorical "series 4".
 *
 * Per `marks-and-anatomy.md`'s "text never wears the data color" rule, the
 * status hue is applied ONLY to the icon glyph; the label text always uses
 * a themed text token (`--text-secondary`, which clears WCAG AA in both
 * themes) so the label itself is never subject to the same sub-3:1 status
 * colors the icon+label pairing exists to mitigate.
 */

export type Status = "good" | "warning" | "serious" | "critical" | "muted";

const STATUS_STYLE: Record<Status, { color: string; icon: string; iconLabel: string }> = {
  good: { color: "var(--status-good)", icon: "✓", iconLabel: "Good" },
  warning: { color: "var(--status-warning)", icon: "▲", iconLabel: "Warning" },
  serious: { color: "var(--status-serious)", icon: "▲", iconLabel: "Serious" },
  critical: { color: "var(--status-critical)", icon: "✕", iconLabel: "Critical" },
  muted: { color: "var(--text-muted)", icon: "…", iconLabel: "Pending" },
};

export function StatusBadge({ status, label }: { status: Status; label: string }) {
  const style = STATUS_STYLE[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium"
      style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
    >
      <span aria-hidden="true" style={{ color: style.color }}>
        {style.icon}
      </span>
      <span>{label}</span>
    </span>
  );
}
