Build Spec: Medicare Advantage Plan Design Simulator (Pilot Prototype)

Codename: Health plan sim for this document: Claude Code (or any coding agent). Execute phases in order. Each phase has acceptance criteria — do not proceed until they pass. Purpose of the prototype: A working demo that simulates how a synthetic Medicare beneficiary population in one county responds to benefit design changes, backtested against real historical enrollment shifts. This is a proof-of-concept for an internal pilot pitch, built entirely on public CMS data.

1. Core Concept
Given a target county and its actual Medicare Advantage competitive landscape, the system:
Ingests real CMS plan and enrollment data for two consecutive plan years (e.g., 2024 and 2025).
Generates a synthetic population of beneficiary personas grounded in county demographics and survey data.
Simulates each persona's plan choice for Year 1 (calibration) and Year 2 (prediction), using a hybrid of a utility-based choice model and LLM-driven persona reasoning.
Backtests: compares predicted Year 2 market-share shifts against actual CMS enrollment data.
Runs counterfactual scenarios: "What if Plan X had cut premium by $15 and dropped dental?" and reports projected share shifts with confidence bounds.
Outputs a leadership-readable report (not raw simulation logs).

2. Hard Constraints
Public data only: No internal, proprietary, or PHI data. Everything must come from CMS public files, Census, or published survey PUFs.
Cost control: LLM calls are the main cost. Design so a full county simulation runs on ≤ 500 LLM calls (persona archetypes + judging), not one call per synthetic member. Simulate 5,000–20,000 members via archetype weighting, not 20,000 API calls.
Reproducibility: Fixed random seeds, pinned dependency versions, all data pulls scripted and cached locally.
use openai as llm provider 

3. tech stack. 
Make it reayd to deploy on vercel 

4. 4. Data Sources (all public)
Dataset	Use	Where
MA Landscape Files (plan year N and N+1)	Premiums, plan names, star ratings, plan types by county	CMS.gov "Medicare Advantage/Part D Landscape" downloads
Plan Benefit Package (PBP) benefits data	Benefit details: MOOP, dental/vision/hearing, OTC/flex, deductibles	CMS PBP public data files
Monthly Enrollment by Contract/Plan/County	Ground truth market shares, YoY switching signal	CMS "Monthly Enrollment by CPSC" files
MA Star Ratings	Quality signal in utility model	CMS Star Ratings data tables
Census ACS 5-year (county)	Age, income, dual-eligibility proxy, race/ethnicity for persona weighting	data.census.gov API
MCBS Public Use File	Beneficiary attitudes: price sensitivity, benefit priorities, switching behavior	CMS MCBS PUF
add any missing ones 

8. Success Definition
The prototype succeeds if it produces one artifact: a backtest report on a real county showing whether a persona-grounded simulation predicted last AEP's actual share shifts better than a naive baseline — plus a live scenario demo. Either backtest outcome (works / doesn't) is a valid result; a rigorous negative result still demonstrates the evaluation methodology, which is the pitch to leadership.