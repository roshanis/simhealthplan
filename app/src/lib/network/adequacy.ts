/**
 * Pure network-adequacy scoring for the hypothetical network designer.
 *
 * Given a set of selected medical groups (from network_inputs.json), a
 * planned enrollment, and the adequacy specialty config
 * (network_standards.json), computes per-specialty: in-network clinician
 * counts, the achieved providers-per-1,000-enrollees ratio, the required
 * count where a target ratio is configured (ceil(target * enrollment /
 * 1000), never below 1), and a presence-based ZCTA coverage share.
 *
 * Deliberately NOT a CMS compliance engine: no drive-time/distance
 * computation, no 90%-of-beneficiaries geo standard, per-group counts
 * double-count clinicians credentialed with multiple selected groups, and
 * target ratios are whatever network_standards.json says (null = report
 * the achieved ratio without a pass/fail). All of this is stated in the UI.
 */

import type { NetworkOrganization, NetworkStandardSpecialty } from "@/lib/data/types";

export interface SpecialtyAssessment {
  key: string;
  label: string;
  clinicians: number;
  achievedRatioPer1000: number;
  targetRatioPer1000: number | null;
  requiredClinicians: number | null;
  /** Covered ZCTAs / total county provider ZCTAs, 0..1. */
  zctaCoverage: number;
  /** true/false only when a target ratio is configured; null otherwise. */
  meetsTarget: boolean | null;
}

export function assessNetwork(
  selectedOrgs: NetworkOrganization[],
  standards: NetworkStandardSpecialty[],
  totalZctas: number,
  enrollment: number,
): SpecialtyAssessment[] {
  const per1000 = enrollment / 1000;

  return standards.map((standard) => {
    const dacSet = new Set(standard.dac_specialties);
    let clinicians = 0;
    const coveredZctas = new Set<number>();

    for (const org of selectedOrgs) {
      for (const [specialty, entry] of Object.entries(org.specialties)) {
        if (!dacSet.has(specialty)) continue;
        clinicians += entry.clinicians;
        for (const idx of entry.zcta_idx) coveredZctas.add(idx);
      }
    }

    const target = standard.target_ratio_per_1000;
    const requiredClinicians = target === null ? null : Math.max(1, Math.ceil(target * per1000));

    return {
      key: standard.key,
      label: standard.label,
      clinicians,
      achievedRatioPer1000: per1000 > 0 ? clinicians / per1000 : 0,
      targetRatioPer1000: target,
      requiredClinicians,
      zctaCoverage: totalZctas > 0 ? coveredZctas.size / totalZctas : 0,
      meetsTarget: requiredClinicians === null ? null : clinicians >= requiredClinicians,
    };
  });
}

/** Total clinicians across the selected groups (all specialties, per-group
 * counts -- see the double-counting note in the module docstring). */
export function totalNetworkClinicians(selectedOrgs: NetworkOrganization[]): number {
  return selectedOrgs.reduce((sum, org) => sum + org.clinicians, 0);
}
