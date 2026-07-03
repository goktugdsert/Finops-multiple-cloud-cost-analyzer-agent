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
- Tracing + eval: LangSmith.
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
