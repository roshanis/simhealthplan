// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { StatusBadge } from "@/components/ui/StatusBadge";

describe("StatusBadge", () => {
  it("renders the label text and an aria-hidden icon glyph", () => {
    render(<StatusBadge status="good" label="Beats no-change" />);
    expect(screen.getByText("Beats no-change")).toBeInTheDocument();
    expect(screen.getByText("✓")).toHaveAttribute("aria-hidden", "true");
  });

  it("applies the status hue ONLY to the icon glyph, never to the label text (marks-and-anatomy.md: 'text never wears the data color')", () => {
    render(<StatusBadge status="critical" label="Loses to no-change" />);
    const icon = screen.getByText("✕");
    const label = screen.getByText("Loses to no-change");
    expect(icon).toHaveStyle({ color: "var(--status-critical)" });
    // The label must NOT carry the raw status hue -- it should resolve to
    // the themed --text-secondary token (inherited from the badge's outer
    // <span>), which is the only token guaranteed to clear WCAG AA in both
    // themes among the status palette.
    expect(label).not.toHaveStyle({ color: "var(--status-critical)" });
    const outerSpan = label.closest("span")?.parentElement;
    expect(outerSpan).toHaveStyle({ color: "var(--text-secondary)" });
  });

  it.each(["good", "warning", "serious", "critical", "muted"] as const)(
    "renders every status variant (%s) without crashing",
    (status) => {
      render(<StatusBadge status={status} label={`label-${status}`} />);
      expect(screen.getByText(`label-${status}`)).toBeInTheDocument();
    },
  );
});
