# mcca-agent — Multi-Cloud Cost Analyzer

A read-only, multi-cloud FinOps agent (LangChain / LangGraph) that normalizes cloud
billing + usage into one **FOCUS-schema** warehouse, then measures, attributes,
explains, and forecasts cloud spend. See [CLAUDE.md](CLAUDE.md) for full scope.

**Core principle (non-negotiable):** the LLM orchestrates and explains but never
produces a cost figure. Every number comes from a deterministic tool (a validated query
or a calculation). If a number can't be traced to a query, it isn't shown.

> Status: **Session 1 — scaffold only.** AWS is the first cloud. Ingestion, the query
> layer, the agent graph, and forecasting are stubbed (`NotImplementedError`) so the
> module boundaries are real. No Azure/GCP yet.

## Architecture (one-way dependencies)

```
ingestion/aws ──┐
                ├──► warehouse (schema + repository interface)
queries ────────┘            ▲
   ▲                         │
tools ───────────────────────┘   (tools run validated queries + calculations only)
   ▲
agent (LangGraph)  ──► tools ONLY
```

- **`warehouse/`** — the data-access layer behind a `WarehouseRepository` interface.
  Postgres in v1 (`postgres.py`); swap to BigQuery/Snowflake later by adding a new
  implementation — no change to `queries/`, `tools/`, or `agent/`.
- **`agent/`** imports only `tools/`; never `boto3`, ingestion, or raw SQL. That import
  boundary makes the core principle structural, not just a prompt rule.

## Prerequisites
- [uv](https://docs.astral.sh/uv/) (manages Python + deps; installs a 3.11+ interpreter)
- Docker (for local Postgres)

## Setup
```bash
cp .env.example .env          # then edit; .env is gitignored, never commit it
uv sync                        # create venv, install deps, write uv.lock
docker compose up -d           # start local Postgres (pinned)
uv run alembic upgrade head    # create the FOCUS schema
```

## Test
```bash
uv run pytest                  # unit tests always run; integration needs Postgres up
uv run pytest -m "not integration"   # unit only
uv run ruff check .            # lint
uv run ruff format .           # format
```

## AWS credentials (read-only, least-privilege)
The agent is read-only. Provide a least-privilege billing role granting only Cost
Explorer read, CUR read (+ S3 read of the CUR bucket), and CloudWatch read — no
write/terminate anywhere. Supply via an AWS profile or env vars in `.env`
(`MCCA_AWS_*`). Never hardcode or commit credentials. See `.env.example`.

## Layout
See [CLAUDE.md](CLAUDE.md) → Conventions → Directory layout.
