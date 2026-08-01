/**
 * "Methodology and limitations" -- every documented modeling
 * compromise, in one accordion. Plain server component: native
 * `<details>`/`<summary>` needs zero client JS for accordion behavior
 * (keyboard-accessible, works with JS disabled, degrades to "everything
 * visible" if CSS fails to load).
 */

interface MethodologyItem {
  id: string;
  title: string;
  body: string;
}

const ITEMS: MethodologyItem[] = [
  {
    id: "ipf-independence",
    title: "Demographic cells assume conditional independence (IPF)",
    body:
      "The 80 archetypes are built by iterative proportional fitting (IPF) of age band x income tier x race/ethnicity against one-way ACS marginals only -- no ACS cross-tabulation of all three axes for Maricopa County's 65+ population was available. IPF finds a joint distribution consistent with the marginals, not the true joint; if the real population has structural correlation the marginals don't capture (e.g. race-conditioned income skew within an age band), that correlation isn't represented.",
  },
  {
    id: "national-mcbs",
    title: "Attitude segments are national, not county-specific",
    body:
      "The four attitude segments (price-sensitive, benefit-maximizer, brand-loyal, health-status-driven) are derived from the national MCBS Public Use File, conditioned only on coarse age (65-74 / 75+) x income (<$25k / >=$25k) strata, then broadcast onto the ACS's finer 4-band x 3-tier demographic grid. MCBS has no county identifier, so these are not Maricopa-specific attitude estimates -- they assume Maricopa beneficiaries share the national distribution of attitudes within each age/income stratum.",
  },
  {
    id: "snp-proxies",
    title: "C-SNP and I-SNP eligibility are explicit proxies, not CMS rules",
    body:
      "D-SNP eligibility (dual_proxy) is a real CMS rule, derived from ACS/CMS income data. I-SNP eligibility is approximated by age_band == '85+' (true I-SNP eligibility requires institutional/long-term-care residence, which isn't observed in this data). C-SNP eligibility is approximated by attitude_segment == 'health_status_driven' (true C-SNP eligibility requires a qualifying chronic-condition diagnosis, also unobserved). Both proxies are documented, explicit, and applied consistently to the choice set and to Year-1 prior-mass renormalization.",
  },
  {
    id: "moop-imputation",
    title: "29 plans needed MOOP imputation",
    body:
      "CMS's Landscape files have gaps in in-network MOOP (maximum out-of-pocket). Where a plan's MOOP was null, 26 plans were backfilled from the same renewed plan's other-year MOOP via the CMS plan crosswalk, and the remaining 3 were imputed as the normalized-plan-type (HMO/PPO/Regional PPO) median MOOP among that year's known values. Imputed rows are flagged (imputed_moop) and marked with * in the market snapshot table.",
  },
  {
    id: "star-imputation",
    title: "15 plans needed star-rating imputation",
    body:
      "CMS placeholder ratings ('Not enough data available' / 'Plan too new to be measured') were imputed with the normalized-plan-type median star rating among that year's known ratings (12 HMO, 3 PPO). Imputed rows are flagged (imputed_star) and marked with * in the market snapshot table.",
  },
  {
    id: "cpsc-suppression",
    title: "CMS suppresses small enrollment cells; imputed to 5",
    body:
      "CMS's Monthly Enrollment by Contract/Plan/County (CPSC) file suppresses any contract-plan-county cell with enrollment <=10, for privacy, replacing it with a literal '*' rather than a number. This pipeline imputes suppressed cells to 5 (the same convention used everywhere enrollment feeds archetype weighting or the choice model) -- a plausible midpoint, not a recovered true value. 3 plans were suppressed in both 2024 and 2025, and are excluded from directional-accuracy scoring (no reliable actual-shift signal either year).",
  },
  {
    id: "b-star-zero",
    title: "The fitted star-rating coefficient (b_star) is exactly 0",
    body:
      "Calibration (multi-start L-BFGS-B against actual 2024 shares) converged to b_star = 0.0 -- star rating carries no independent explanatory power in this fitted model, once premium, MOOP, benefits, plan type, and inertia are accounted for. This is a real calibration result, not a bug: in the scenario demo, changing a plan's star rating has zero effect on its predicted share, for exactly this reason (verified by a regression test).",
  },
  {
    id: "inertia-dominance",
    title: "Inertia dominates the fitted model (b_inertia ~= 37)",
    body:
      "The fitted inertia coefficient (b_inertia ~= 37.0) is an order of magnitude larger than every other coefficient. In practice this means an archetype's Year-1 plan choice is the single strongest predictor of its Year-2 choice -- attribute changes (premium, benefits, stars) shift probabilities only at the margins for archetypes with strong prior mass on a given plan, and matter much more for archetypes without an established incumbent. This is consistent with the headline result: a 'nothing changes' naive baseline is hard to beat on magnitude precisely because switching is rare.",
  },
  {
    id: "coefficient-jitter",
    title: "Confidence bounds use heuristic +/-10% coefficient jitter, not formal standard errors",
    body:
      "The Monte Carlo p10/p50/p90 bounds shown throughout (backtest and scenario demo) are generated by jittering each fitted coefficient by a Normal(0, max(10% of |coefficient|, 0.01)) draw and each archetype's population weight log-normally, then re-running the full choice model per draw. This is a deliberately simple sensitivity band, not a formally derived standard error from the calibration's loss surface (e.g. no Hessian-based covariance was computed) -- treat the bands as 'here's how sensitive this number is to a plausible coefficient wobble,' not a rigorous confidence interval. Because softmax is nonlinear in the coefficients, the jittered median can sit meaningfully off the point estimate for plans with concentrated inertia effects (e.g. SNP plans with a narrow eligible archetype set) -- an expected property of this method, not an error.",
  },
  {
    id: "physician-no-network-linkage",
    title: "Physician data carries no plan-network linkage (context only)",
    body:
      "The physician-supply section is built from CMS's Doctors and Clinicians National Downloadable File -- a public roster of clinicians, their specialties, group practices, and practice addresses. CMS publishes no dataset linking physicians to specific Medicare Advantage plan networks, so this data is descriptive market context only: it does not feed the choice model, and the scenario tool cannot simulate adding or dropping a physician from a plan's network. County filtering uses a documented ZIP~=ZCTA proxy (each ZCTA assigned to its maximum-land-area county via the Census 2020 relationship file), since the roster carries ZIP codes but no county field.",
  },
  {
    id: "llm-blend-bound",
    title: "The (pending) LLM blend is bounded to a small utility adjustment (alpha = 0.35)",
    body:
      "When the LLM persona pass runs, each archetype's ranked LLM choice output adds an additive utility bonus of at most alpha = 0.35 to its top-ranked alternative (linearly down to 0 at the bottom of its ranking) -- small relative to this model's typical utility spread (e.g. b_inertia ~= 37 means even a middling prior-mass difference outweighs the full rank bonus). The LLM can nudge relative attractiveness within an archetype's consideration set; it cannot override the calibrated economic coefficients.",
  },
];

export function Methodology() {
  return (
    <section aria-labelledby="methodology-heading" className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <h2 id="methodology-heading" className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
          Methodology and limitations
        </h2>
        <p className="max-w-3xl text-sm" style={{ color: "var(--text-secondary)" }}>
          The assumptions and shortcuts behind this model, listed plainly. Open any item for details.
        </p>
      </div>

      <div className="flex flex-col divide-y rounded-xl border" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
        {ITEMS.map((item) => (
          <details key={item.id} className="accordion-item group px-4 py-3" style={{ borderColor: "var(--border)" }}>
            <summary className="flex items-center justify-between gap-3 text-sm font-medium" style={{ color: "var(--text-primary)" }}>
              {item.title}
              <span className="accordion-chevron shrink-0" style={{ color: "var(--text-muted)" }} aria-hidden="true">
                ›
              </span>
            </summary>
            <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
              {item.body}
            </p>
          </details>
        ))}
      </div>
    </section>
  );
}
