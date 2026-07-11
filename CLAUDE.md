# Multi-Cloud Cost Analyzer Agent

## What this is
A multi-cloud FinOps agent (LangChain / LangGraph) that connects to AWS, Azure,
and GCP, normalizes their billing + usage data into one FOCUS-schema warehouse,
and then measures, attributes, explains, and forecasts cloud spend. Read-only:
the agent never modifies or terminates infrastructure.

## Core principle (non-negotiable)
The LLM orchestrates and explains. It NEVER produces a cost figure from its own
reasoning. Every number returned to a user comes from a deterministic tool
(a SQL query or a calculation), never from the model. If a number can't be
traced to a query, it doesn't get shown.

## The loop the agent implements
measure spend → attribute to team/service/environment → detect (both spikes AND
steady structural waste) → explain WHY it changed → forecast → track vs budget →
route findings to an owner with a recommended action.

## v1 scope
- All three clouds, but built ONE cloud end-to-end first (AWS), then Azure and
  GCP against the same proven FOCUS mapping. Do not build three pipelines in
  parallel.
- Read-only throughout. Recommend actions; never execute them.
- Two pillars done well: unified visibility, and predictive budgeting.
- A FIXED, pre-tested set of cost queries. NOT open-ended text-to-SQL.
- Attribution built into the data model from line one. Untagged spend shows
  honestly as "unattributed" — reserve the column now, defer allocation policy.
- Forecasting at sensible granularity, always showing uncertainty.
- LangSmith tracing wired in from day one.

## Explicitly OUT of v1 (do not build these yet)
- Governance policy engine.
- Optimization with auto-actioning. (v1 is recommend-only; a human approves.)
- Open-ended natural-language querying / arbitrary LLM-written SQL.
  (Comes later behind a semantic layer.)
- RAG vector store. (Document knowledge base for pricing docs / policies —
  additive, and no v1 pillar needs it. Note: even when added later, RAG is for
  qualitative/knowledge answers only. It must NEVER be a source of cost figures;
  numbers always come from deterministic warehouse queries.)
- "Real-time" — this is near-real-time / daily, and is framed that way.

## Where quality lives
Not feature count. Two things: (1) numbers that are provably correct — validate
every query against the AWS Cost Explorer console until they match exactly;
(2) clean cross-cloud normalization — a dollar means the same thing on all three
clouds (handle discounts, credits, amortization, blended vs unblended).

## Build order
1. Access + FOCUS schema — least-privilege billing roles; lock the mapping.
2. AWS end-to-end — ingestion (Cost & Usage Report / Cost Explorer) → normalized
   warehouse, messy cases handled (RIs, Savings Plans, credits, amortization).
3. Query layer — fixed question set as deterministic, validated tools.
4. Agent orchestration — LangGraph wiring the LLM to those tools.
5. Azure and GCP — same pipeline, same FOCUS mapping.
6. Forecasting — historical spend, sensible granularity, uncertainty shown.
7. Surface + eval — dashboard/report + a small curated eval set.

## Stack
- Language: Python.
- Framework: LangChain / LangGraph. LLM as reasoning engine only.
- Warehouse: Postgres for v1 (local, sufficient at dev scale). Keep warehouse
  access behind a data-access layer so it can be swapped for BigQuery /
  Snowflake later without touching agent logic.
- Schema: FOCUS (FinOps Open Cost & Usage Specification).
- Forecasting: Prophet or statsmodels (ARIMA).
- Tracing + eval: Langfuse (free cloud tier or self-hosted; config-driven, off by
  default). [Deviation from the original LangSmith choice, per project decision.]
- Cloud #1: AWS (Cost & Usage Report + Cost Explorer + CloudWatch).

## Conventions
- Package manager: `uv` (pyproject.toml + uv.lock). Common commands:
  `uv sync`, `uv run pytest`, `uv run alembic upgrade head`.
- Test command: `uv run pytest` (unit tests need no DB; `-m integration`
  requires a live Postgres via `docker compose up -d`).
- Lint / format: `ruff` + `ruff format` (`uv run ruff check .`).
- Secrets: read-only, least-privilege IAM; never hardcode; use env vars / a
  secrets manager. Never commit credentials. Config is loaded from env/.env via
  `pydantic-settings` (`MCCA_` prefix); `.env` is gitignored.
- Data-access: SQLAlchemy Core + Alembic behind a `WarehouseRepository` interface
  so Postgres can be swapped later without touching agent logic.
- Directory layout:
  ```
  src/mcca/
    config.py, logging.py, __main__.py
    warehouse/   schema.py (FOCUS tables) · models.py (FocusRecord) ·
                 engine.py · repository.py (interface) · postgres.py (impl)
    ingestion/aws/   client · cost_explorer · normalize · loader
    queries/     registry.py · definitions/   (fixed, validated query set)
    tools/       cost_tools.py   (LangChain tools — the agent's only numeric source)
    agent/       graph.py · state.py · prompts.py   (LangGraph; imports tools/ ONLY)
    forecasting/     (build step 6)
  migrations/    Alembic (env.py, versions/)
  tests/         unit/ · integration/ · fixtures/
  ```
  Dependency rule (enforces the core principle): `agent → tools → queries →
  warehouse-interface`; `ingestion → warehouse-interface`. `agent/` never imports
  ingestion, boto3, or raw SQL.

---

# IMPLEMENTATION STATUS (as-built) — updated end of build

**TL;DR:** v1 is **feature-complete and committed**. All 7 build steps done, all 3
clouds, the full loop, both pillars, report + web chat UI + eval + Langfuse tracing.
**113 tests passing, ruff clean.** Runs on **synthetic data only** (no real cloud
accounts — this is a permanent project decision, see "Deviations"). The only things
NOT built require real cloud data.

## Build order — all done
1. ✅ Access + FOCUS schema (`warehouse/schema.py`: `focus_costs` + `budgets` tables).
2. ✅ AWS end-to-end (`ingestion/aws/`: client, cost_explorer, normalize, loader).
3. ✅ Query layer (`queries/registry.py` + `queries/definitions/`).
4. ✅ Agent (`agent/graph.py` LangGraph loop; `tools/cost_tools.py`).
5. ✅ Azure + GCP (`ingestion/azure/`, `ingestion/gcp/`) — same FOCUS mapping.
6. ✅ Forecasting (`forecasting/`: SARIMAX + linear fallback, uncertainty shown).
7. ✅ Surface + eval (`surface/report.py` HTML, `surface/web.py` chat UI, `eval/`).

## The loop — all 7 stages implemented
measure (`queries`) → attribute (`ingestion/attribution.py` tags→x_*) → detect
(`detection/`) → explain (`analysis/drivers.py`) → forecast (`forecasting/`) →
track-vs-budget (`budgets/`) → route-to-owner (`routing/`).

## As-built directory layout (extends the one above)
```
src/mcca/
  config.py logging.py tracing.py __main__.py      # tracing.py = Langfuse
  warehouse/  schema.py(focus_costs+budgets) models.py engine.py
              repository.py(interface: execute/insert/create_schema/fetch_all) postgres.py
  ingestion/
    attribution.py                                  # shared tag->x_* policy (cross-cloud)
    aws/    client cost_explorer normalize loader   # Cost Explorer shape
    azure/  client cost_management normalize loader  # Cost Management Query (columnar)
    gcp/    client billing_export normalize loader    # BigQuery billing export (nested)
    synthetic/  generator.py(AWS) azure.py gcp.py client.py seed.py
                # synthetic providers emit each cloud's native shape; deterministic per seed
  queries/  registry.py definitions/{spend,attribution,trends}.py
  tools/    cost_tools.py     # 12 agent tools + catalog_hint()
  agent/    graph.py state.py model.py prompts.py   # model.py = provider factory
  forecasting/  model.py service.py
  detection/    detector.py service.py
  budgets/      model.py store.py service.py
  analysis/     drivers.py                          # explain-why (cost drivers)
  routing/      router.py                           # findings -> owner + recommendation
  surface/      report.py(HTML) web.py(FastAPI chat)
  eval/         dataset.py runner.py
migrations/  0001_focus_schema.py 0002_budgets.py
```

## Registered queries (queries/registry.py)
Agent-facing: `total_spend, spend_by_service, spend_by_provider,
spend_by_charge_category, daily_spend, monthly_spend, spend_by_team,
spend_by_environment, month_over_month`.
Internal (agent_facing=False, power tools/features): `daily_spend_by_service,
charge_date_bounds, service_owners, service_catalog`.
`run_query(repo, name, params)` validates params + carries provenance; repo.execute()
runs prepared Core statements only (no string SQL).

## Agent tools (tools/cost_tools.py) — 12
One per agent-facing query, plus `forecast_spend, detect_anomalies, spend_vs_budget,
explain_change, route_findings`. `get_cost_tools(repo)` builds them; `catalog_hint(repo)`
injects the exact provider/service names into the system prompt at build time.

## LLM provider — config-driven (agent/model.py)
`MCCA_LLM_PROVIDER` ∈ {google, ollama, anthropic, openai}. **Currently: ollama /
qwen3.5:9b** (local, free, unlimited, ~80 s/answer on a 6 GB GPU). Gemini
`gemini-2.5-flash-lite` kept as commented fallback in `.env` (fast but free tier is
20 req/day/model). Switching = flip two `.env` lines. Ollama at
`%LOCALAPPDATA%\Programs\Ollama`; model pulled (6.6 GB).

## Entry points / how to run
`docker compose up -d` → `uv run alembic upgrade head` → `uv run mcca-seed` (all 3
clouds, ~$232k, sets a $9k budget). Then: `uv run mcca-web` (chat UI at
127.0.0.1:8000), `uv run mcca "question"` (CLI), `uv run mcca-report` (HTML),
`uv run mcca-eval` (tool-selection score), `uv run pytest` (113 tests).
`mcca-seed --cloud {aws,azure,gcp,all}`. NOTE: `uv run pytest` DROPS the seeded data
(integration fixtures drop_all at teardown) — re-seed afterward.

## Observability
Langfuse (`tracing.py`), config-driven via `MCCA_LANGFUSE_*`, off by default; enabled
in the dev `.env`. Applied at both graph.invoke sites (CLI + web) with flush on exit.

## Reliability work done (tool selection / grounding)
- System prompt (`agent/prompts.py`): tool-selection rules (aggregates vs per-service),
  service-name disambiguation ("compute" per cloud), "ask if ambiguous".
- Sharpened tool descriptions (total_spend/monthly_spend = ALL-services totals).
- Dynamic **service catalog** injected into the prompt (exact names, never invent).
- Wide test vs qwen3.5:9b scored **11/11 tool selection**.

## KNOWN ISSUES / nits (all narration, never fabricated numbers)
The "numbers only from tools" guarantee HOLDS — every figure matches the deterministic
query/tool. But the local 9B model sometimes **mis-narrates** correct numbers:
- **Forecast narration bug (confirmed):** on the 30-day forecast it (a) INVERTED
  weekday/weekend — real: weekdays HIGH (~$1,060/day), weekends LOW (~$870); and
  (b) HALLUCINATED a "July 4th holiday / calendar effect". Our SARIMAX has ONLY weekly
  (7-day) seasonality — no holiday awareness. Numbers were exact; the story was wrong.
- Occasionally returns an **empty final answer** (tool ran, no narration) — retry fixes.
- Sometimes mislabels the forecast interval (it's **80%**, said 90%).
These drop sharply with a stronger model. NOT yet fixed.

## WHAT'S MISSING
Requires real cloud accounts (out of scope by decision — synthetic-only):
- Real ingestion **clients** are `NotImplementedError` stubs (aws/azure/gcp `client.py`).
  Real path = swap the synthetic client for a real SDK client; normalize/loader unchanged.
- **Console validation** (match real Cost Explorer/Cost Management/BigQuery exactly) —
  RETIRED as a goal (no accounts). Synthetic data validates plumbing + math, not real $$.
- **CUR / line-item** granularity (resource-level, richer tags) — CE/Query/export
  aggregated shapes used instead.

Optional polish (no real data needed, NOT done):
1. Forecast-narration guardrail: prompt the agent that the model captures only weekly
   seasonality (no holidays) + read weekend/weekday direction from values; and enrich
   `forecast_spend` output with day-of-week + interval% so it can't mis-narrate.
2. CI (GitHub Actions to run tests on push).
3. README (what-it-is / how-to-run / demo prompts).
4. `qwen3.5:4b` as a faster local option.

## Deviations from the original plan
- **Tracing: Langfuse instead of LangSmith** (user decision).
- **Synthetic-only** — no real cloud accounts ever; real-console validation retired.
- **"Surface" built as an interactive web chat UI** (`mcca-web`, FastAPI) in addition to
  the static HTML report — this is the user-facing "dashboard".

## Env quirks (Windows dev machine)
`uv` at `~/.local/bin` (not on PATH in fresh tool shells — prepend it). Docker Desktop
needs manual start. Python 3.14 via uv. `.env` holds real Gemini + Langfuse keys
(gitignored, verified NOT committed). Repo is PUBLIC on GitHub — never commit `.env`.
