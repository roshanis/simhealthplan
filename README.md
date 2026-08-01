# simhealthplan

Medicare Advantage plan-design choice simulator — a pilot prototype built
entirely on public CMS/Census data. It models how Medicare-eligible consumers
in **Maricopa County, AZ** choose among available MA plans, and backtests
those simulated choices against the observed **2024 → 2025** enrollment
shifts (the fall-2024 AEP). It also runs live counterfactual scenarios
("what if Plan X cut premium $15 and dropped dental?") with Monte Carlo
confidence bounds.

The project is split into two halves:

- A **Python pipeline** that runs locally: it ingests CMS plan/enrollment
  data, parses plan benefit designs, builds weighted consumer archetypes,
  runs a calibrated multinomial-logit choice model (optionally blended with
  `gpt-5.6-luna` persona reasoning under a hard ≤500-call budget), backtests
  against real enrollment changes, and exports results as static JSON.
- A **Next.js app** that reads that exported JSON and renders the
  leadership-readable backtest report plus a live scenario demo — display
  and pure-math recompute only, deployed to Vercel.

## Headline result (honest by design)

Calibrated on 2024 and scored against actual March-2025 enrollment:

| Model variant | Size-weighted MAE | Directional accuracy |
|---|---|---|
| Choice model (logit) | 1.235pp | **71.4%** |
| Naive: no change | **0.419pp** | 41.8% |
| Naive: trend | 0.639pp | 61.5% |

The model **does not beat the no-change baseline on magnitude** (Maricopa's
2024→2025 market was sticky) but **substantially beats both baselines on
direction**. Per the build spec, either outcome is a valid result — the
deliverable is the rigorous evaluation methodology. The LLM-blended variant
is pending (requires `OPENAI_API_KEY`).

## How it works

1. **Ingest** (`make ingest`) — scripted, cached, sha256-manifested downloads:
   CMS MA Landscape (CY2024/CY2025, schema-break normalized), Monthly
   Enrollment by CPSC (Mar 2023/2024/2025), MA county penetration, PBP
   benefits targeted extract, plan crosswalk, SSA↔FIPS crosswalk, Census ACS
   5-year (keyless flat files from www2.census.gov), MCBS Survey File PUF 2023.
2. **Archetypes** (`make archetypes`) — 80 weighted personas: ACS demographic
   marginals × national MCBS attitude segments via iterative proportional
   fitting; weights sum to the county's 771,696 Medicare eligibles; Year-1
   prior-plan distributions IPF-calibrated to actual 2024 shares.
3. **Choice model** (`make calibrate`) — multinomial logit over premium, MOOP,
   dental/vision/hearing/OTC, stars, plan type, inertia, and an outside
   option; hard D-SNP/I-SNP/C-SNP eligibility filters; multi-start L-BFGS-B
   calibration (Year-1 in-sample fit: 0.18pp weighted MAE).
4. **LLM persona layer** (`make personas`) — one `gpt-5.6-luna` choice call +
   one backstory call per archetype (~160 calls, disk-cached and committed so
   reruns are free and deterministic; hard 500-call ceiling).
5. **Backtest** (`make backtest`) — predicted vs actual 2025 share shifts vs
   two naive baselines; `beats_naive` computed by an explicit rule, never
   hand-set; N=1000 Monte Carlo confidence bounds.
6. **Export + app** (`make export`) — trimmed JSON into `app/src/data/`; the
   TypeScript engine (golden-parity-tested against Python at 1e-9; observed
   ~1e-15) recomputes scenarios live in the browser/API with zero LLM calls.

## Monorepo layout

```
simhealthplan/
├── pipeline/                 # Python 3.12 project (managed by uv)
│   ├── config/               #   settings (county, years, seed, model config)
│   ├── ingest/               #   CMS/Census/MCBS downloads (cache-first)
│   ├── parse/                #   parsing to validated Maricopa parquet tables
│   ├── archetypes/           #   IPF-weighted consumer archetype construction
│   ├── choice_model/         #   utility, choice sets, calibration, Y2 predict
│   ├── llm/                  #   gpt-5.6-luna client, prompts, bounded blend
│   ├── backtest/             #   metrics, baselines, Monte Carlo bounds
│   ├── export/               #   golden fixture + app JSON export
│   └── tests/                #   430+ tests (unit + integration)
├── app/                      # Next.js app (TypeScript, App Router) -> Vercel
│   ├── src/lib/choice-model/ #   1:1 TS port of the Python engine
│   └── src/data/             #   pipeline-exported JSON lands here
├── shared/golden/            # Python<->TS parity fixture (17 cases)
├── data/
│   ├── raw_cache/            #   gitignored: ~900MB raw source downloads
│   ├── interim/              #   gitignored: intermediate parquet
│   ├── processed/            #   tracked: canonical JSON artifacts
│   └── cache/llm/            #   tracked: cached LLM responses (reproducible)
└── Makefile                  # ingest | archetypes | calibrate | personas | backtest | export | test
```

## Quickstart

### Pipeline (Python, local only)

```bash
cd pipeline
uv sync
uv run pytest        # hermetic unit tests pass with no data downloaded
cd .. && make ingest # downloads + parses all sources (~900MB, cache-first)
make archetypes calibrate backtest
```

Copy `pipeline/.env.example` to `pipeline/.env` and set `OPENAI_API_KEY` only
for the LLM persona pass (`make personas`); everything else runs keyless.

### App (Next.js, deploys to Vercel)

```bash
cd app
npm install
npm test -- --run
npm run dev
```

The app builds and serves the full report with **zero environment variables**.
`ENABLE_LIVE_LLM` + `OPENAI_API_KEY` gate an optional live-narrative feature.

> **Vercel setup:** this is a monorepo — when configuring the Vercel project,
> set **Root Directory to `app/`** so Vercel builds and deploys only the
> Next.js app, not the Python pipeline.

## Reproducibility

Fixed seed (42) everywhere; pinned dependencies (`uv.lock`, `package-lock.json`);
every download logged with URL + sha256 in `data/raw_cache/manifest.json`;
LLM responses disk-cached and committed (warm reruns make zero API calls);
processed artifacts rebuild byte-identically.

## Data sources (all public)

CMS MA/Part D Landscape · CMS Monthly Enrollment by CPSC · CMS MA State/County
Penetration · CMS PBP Benefits · CMS Plan Crosswalks · CMS Star Ratings (via
landscape) · Census ACS 5-year · CMS MCBS Survey File PUF · NBER SSA↔FIPS
crosswalk. Known limitations (2024 SNP MOOP gap, CPSC small-cell suppression,
national-not-county MCBS attitudes, SNP eligibility proxies) are documented in
the report's methodology sidebar and in `data/processed/*.json` metadata.
