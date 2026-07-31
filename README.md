# simhealthplan

Medicare Advantage plan-design choice simulator. Models how Medicare-eligible
consumers in **Maricopa County, AZ** choose among available MA plans, and
backtests those choices against observed 2024 → 2025 enrollment shifts.

The project is split into two halves:

- A **Python pipeline** that runs locally: it ingests CMS plan/enrollment
  data, parses plan benefit designs, builds consumer archetypes, runs a
  choice model (optionally LLM-assisted), backtests against real enrollment
  changes, and exports results as static JSON.
- A **Next.js app** that reads that exported JSON and renders it — display
  only, no business logic, deployed to Vercel.

## Monorepo layout

```
simhealthplan/
├── pipeline/                 # Python 3.12 project (managed by uv)
│   ├── config/                #   settings (county, years, seed, model config)
│   ├── ingest/                 #   CMS data downloads / raw ingestion
│   ├── parse/                   #   plan benefit design parsing
│   ├── archetypes/               #   consumer archetype construction
│   ├── choice_model/              #   plan choice simulation
│   ├── llm/                        #   LLM-assisted persona / reasoning calls
│   ├── backtest/                    #   2024 -> 2025 backtest evaluation
│   ├── export/                       #   writes JSON consumed by app/src/data
│   └── tests/
├── app/                       # Next.js app (TypeScript, App Router) -> Vercel
│   └── src/data/               #   pipeline-exported JSON lands here
├── shared/golden/             # golden fixtures shared across pipeline + app
├── data/                      # local pipeline data (see .gitignore)
│   ├── raw_cache/               #   gitignored: raw downloaded source data
│   ├── interim/                  #   gitignored: intermediate processing state
│   ├── processed/                 #   tracked: processed outputs
│   └── cache/llm/                  #   tracked: cached LLM responses
└── Makefile                  # convenience targets across both halves
```

## Quickstart

### Pipeline (Python, local only)

```bash
cd pipeline
uv sync
uv run pytest
```

Copy `pipeline/.env.example` to `pipeline/.env` and set `OPENAI_API_KEY` if
running any LLM-assisted steps.

### App (Next.js, deploys to Vercel)

```bash
cd app
npm install
npm run dev
```

Copy `app/.env.example` to `app/.env.local` if you need to override
`OPENAI_API_KEY` or `ENABLE_LIVE_LLM` locally.

> **Vercel setup:** this is a monorepo — when configuring the Vercel project,
> set **Root Directory to `app/`** so Vercel builds and deploys only the
> Next.js app, not the Python pipeline.

## Status

Scaffolding phase — no business logic implemented yet.
