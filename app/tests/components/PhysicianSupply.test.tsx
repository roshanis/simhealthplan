// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { PhysicianSupply } from "@/components/report/PhysicianSupply";
import type { PhysiciansFile } from "@/lib/data/types";

// Vitest runs without globals, so testing-library's auto-cleanup never
// registers; without this the DOM accumulates across tests in this file.
afterEach(cleanup);

const UNAVAILABLE: PhysiciansFile = {
  available: false,
  totals: null,
  top_specialties: [],
  top_organizations: [],
};

const AVAILABLE: PhysiciansFile = {
  available: true,
  metadata: { county_fips: "04013", network_linkage: false },
  totals: {
    clinicians: 12345,
    organizations: 678,
    practice_locations: 23456,
    specialties: 90,
    telehealth_share: 0.42,
  },
  top_specialties: [
    { specialty: "INTERNAL MEDICINE", clinicians: 1500 },
    { specialty: "FAMILY PRACTICE", clinicians: 1200 },
  ],
  top_organizations: [
    { org_name: "BANNER HEALTH", clinicians: 900 },
    { org_name: "VALLEY CARE MEDICAL GROUP", clinicians: 400 },
  ],
};

describe("PhysicianSupply", () => {
  it("renders the pending placeholder when the pipeline hasn't generated the data", () => {
    render(<PhysicianSupply physicians={UNAVAILABLE} />);
    expect(screen.getByText(/pending the ingest pass/i)).toBeInTheDocument();
  });

  it("renders totals and title-cased top lists once available", () => {
    render(<PhysicianSupply physicians={AVAILABLE} />);

    expect(screen.getByText("12,345")).toBeInTheDocument();
    expect(screen.getByText("678")).toBeInTheDocument();
    expect(screen.getByText("42.0%")).toBeInTheDocument();

    // ALL-CAPS CMS names are title-cased for display.
    expect(screen.getByText("Internal Medicine")).toBeInTheDocument();
    expect(screen.getByText("Banner Health")).toBeInTheDocument();
    expect(screen.queryByText(/pending the ingest pass/i)).not.toBeInTheDocument();
  });
});
