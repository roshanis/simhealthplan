import { describe, expect, it } from "vitest";

import { assessNetwork, totalNetworkClinicians } from "@/lib/network/adequacy";
import type { NetworkOrganization, NetworkStandardSpecialty } from "@/lib/data/types";

const ORGS: NetworkOrganization[] = [
  {
    org_pac_id: "111",
    org_name: "BANNER HEALTH",
    clinicians: 20,
    specialties: {
      "INTERNAL MEDICINE": { clinicians: 12, zcta_idx: [0, 1] },
      "FAMILY PRACTICE": { clinicians: 5, zcta_idx: [1] },
      "CARDIOVASCULAR DISEASE (CARDIOLOGY)": { clinicians: 3, zcta_idx: [0] },
    },
  },
  {
    org_pac_id: "222",
    org_name: "VALLEY CARE",
    clinicians: 4,
    specialties: {
      "INTERNAL MEDICINE": { clinicians: 4, zcta_idx: [2] },
    },
  },
];

const STANDARDS: NetworkStandardSpecialty[] = [
  {
    key: "primary_care",
    label: "Primary care",
    dac_specialties: ["FAMILY PRACTICE", "INTERNAL MEDICINE"],
    target_ratio_per_1000: 1.67,
    target_source: "test",
  },
  {
    key: "cardiology",
    label: "Cardiology",
    dac_specialties: ["CARDIOVASCULAR DISEASE (CARDIOLOGY)"],
    target_ratio_per_1000: 0.27,
    target_source: "test",
  },
  {
    key: "dermatology",
    label: "Dermatology",
    dac_specialties: ["DERMATOLOGY"],
    target_ratio_per_1000: null,
    target_source: null,
  },
];

const TOTAL_ZCTAS = 4;

describe("assessNetwork", () => {
  it("sums clinicians across selected groups per mapped specialty", () => {
    const [pcp, cardio] = assessNetwork(ORGS, STANDARDS, TOTAL_ZCTAS, 10_000);
    expect(pcp.clinicians).toBe(21); // 12 + 5 + 4
    expect(cardio.clinicians).toBe(3);
  });

  it("computes required counts as ceil(ratio x enrollment / 1000) and pass/fail", () => {
    const [pcp, cardio] = assessNetwork(ORGS, STANDARDS, TOTAL_ZCTAS, 10_000);
    expect(pcp.requiredClinicians).toBe(17); // ceil(1.67 * 10)
    expect(pcp.meetsTarget).toBe(true);
    expect(cardio.requiredClinicians).toBe(3); // ceil(0.27 * 10) = 3
    expect(cardio.meetsTarget).toBe(true);

    const [pcpBig, cardioBig] = assessNetwork(ORGS, STANDARDS, TOTAL_ZCTAS, 50_000);
    expect(pcpBig.requiredClinicians).toBe(84); // ceil(1.67 * 50)
    expect(pcpBig.meetsTarget).toBe(false);
    expect(cardioBig.meetsTarget).toBe(false);
  });

  it("requires at least 1 provider even at tiny enrollment when a target exists", () => {
    const [pcp] = assessNetwork([], STANDARDS, TOTAL_ZCTAS, 100);
    expect(pcp.requiredClinicians).toBe(1);
    expect(pcp.meetsTarget).toBe(false);
  });

  it("reports null pass/fail when no target ratio is configured", () => {
    const derm = assessNetwork(ORGS, STANDARDS, TOTAL_ZCTAS, 10_000)[2];
    expect(derm.clinicians).toBe(0);
    expect(derm.targetRatioPer1000).toBeNull();
    expect(derm.requiredClinicians).toBeNull();
    expect(derm.meetsTarget).toBeNull();
  });

  it("computes ZCTA coverage as the union across selected groups", () => {
    const [pcp, cardio] = assessNetwork(ORGS, STANDARDS, TOTAL_ZCTAS, 10_000);
    expect(pcp.zctaCoverage).toBeCloseTo(3 / 4); // zctas 0,1,2 of 4
    expect(cardio.zctaCoverage).toBeCloseTo(1 / 4);
  });

  it("achieved ratio scales with enrollment", () => {
    const [pcp] = assessNetwork(ORGS, STANDARDS, TOTAL_ZCTAS, 10_000);
    expect(pcp.achievedRatioPer1000).toBeCloseTo(2.1);
  });
});

describe("totalNetworkClinicians", () => {
  it("sums per-group clinician counts", () => {
    expect(totalNetworkClinicians(ORGS)).toBe(24);
    expect(totalNetworkClinicians([])).toBe(0);
  });
});
