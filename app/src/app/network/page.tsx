/**
 * Hypothetical provider-network designer: assemble a draft network from
 * real Maricopa medical groups (CMS Doctors and Clinicians roster) and
 * score it against configurable adequacy targets. Server component wrapper;
 * all interaction lives in NetworkDesigner (client). Follows the
 * personas/physicians graceful-absence pattern until `make ingest` has run.
 */

import Link from "next/link";

import { NetworkDesigner } from "@/components/network/NetworkDesigner";
import { networkInputs, networkStandards } from "@/lib/data/loaders";

export const metadata = {
  title: "Network designer — simhealthplan",
};

export default function NetworkPage() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-10 sm:px-8">
      <header className="flex flex-col gap-4">
        <nav className="flex items-center justify-between text-sm" style={{ color: "var(--text-secondary)" }}>
          <span className="font-semibold" style={{ color: "var(--text-primary)" }}>
            simhealthplan
          </span>
          <Link href="/" className="rounded-md border px-3 py-1.5" style={{ borderColor: "var(--border)" }}>
            ← Back to the report
          </Link>
        </nav>
        <div className="flex flex-col gap-3">
          <h1 className="text-3xl font-semibold tracking-tight" style={{ color: "var(--text-primary)" }}>
            Network designer
          </h1>
          <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
            Sketch a provider network for a hypothetical Maricopa County plan: pick real medical groups from
            CMS&rsquo;s public clinician roster, set a planned enrollment, and see how the draft network stacks up
            against per-specialty provider targets. A design sketchpad, not a CMS filing — see the notes under the
            results.
          </p>
        </div>
      </header>

      {networkInputs.available ? (
        <NetworkDesigner inputs={networkInputs} standards={networkStandards} />
      ) : (
        <div
          className="rounded-lg border px-3 py-2 text-xs"
          style={{ borderColor: "var(--border)", background: "var(--surface-2)", color: "var(--text-secondary)" }}
        >
          Network data is <strong>pending the ingest pass</strong> (<code>make ingest</code> then{" "}
          <code>make export</code>, which downloads CMS&rsquo;s Doctors and Clinicians roster). This page fills in
          automatically once it has run.
        </div>
      )}
    </div>
  );
}
