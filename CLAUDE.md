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

# IMPLEMENTATION STATUS (as-built) — updated after the synthetic-data hardening pass

**TL;DR:** v1 is **feature-complete and validated on synthetic data.** All 7 build steps
done, all 3 clouds, the full loop, both pillars, report + web chat UI + eval + Langfuse
tracing. **223 tests passing (+1 explicitly-skipped live check), ruff clean, CI on push.**
Runs on **synthetic data only** (no real cloud accounts — a standing project decision).

Honest framing (do not overstate): "validated" means **provably correct against our own
synthetic ground truth**, not reconciled to a real cloud bill. Three things remain genuine
**open v1 debts that require real billing data** — they are NOT done and must not be marked
done: (1) reconcile-to-console, (2) real-console confirmation of the full normalization
(RI/SP/credits/blended), (3) the live least-privilege access-scoping check. See the
**"Open v1 debts (require real data)"** section at the bottom. Everything closeable on
synthetic data has been closed and tested.

## Hardening pass (done on synthetic data — see "Open v1 debts" for what's still blocked)
- **Estimate→final reconciliation:** ingestion upserts on a natural billing-line key
  (`FocusRecord.natural_key()`), so re-ingesting a period corrects instead of double-counting
  and an estimate is overwritten by its final. `is_estimated` + `line_key` columns
  (migration `0003`). Proven: `tests/integration/test_reconciliation_seed.py`.
- **Numeric faithfulness:** `eval/numeric.py` (`mcca-eval-numeric`) re-computes every fixed
  query independently from the raw rows and asserts exact agreement (9/9); `eval/faithfulness.py`
  flags any dollar figure in an agent answer that traces to no tool output. Proven:
  `tests/integration/test_numeric_faithfulness_seed.py`, `tests/unit/test_faithfulness.py`.
- **Completed normalization:** Savings Plan line items + Azure credit/adjustment lines are
  now emitted and normalized; `commitment_discount_*` columns populated; blended cost captured
  in `x_blended_cost` (migration `0004`, never billed — billed stays unblended); `list_cost`
  ingested so list→billed→effective is representable. Proven: `tests/integration/test_messy_cases_seed.py`.
- **Access scoping:** read-only session-factory precedence, read-only `ce`-only client, and a
  structural "no infra-mutating call / no cloud SDK in agent+tools" guarantee are tested.
  Proven: `tests/unit/test_access_scoping.py` (live cred check skipped — see debts).
- **Forecast-narration guardrail + runtime faithfulness guard:** the confirmed forecast
  mis-narration (weekday/weekend inversion, hallucinated holiday, wrong interval %) is
  neutralized by `summarize_forecast` + prompt rules; and every live `mcca-web`/`mcca` answer
  is checked so a fabricated figure is surfaced, not silently trusted. Proven:
  `tests/unit/test_forecasting.py`, `tests/unit/test_cost_tools.py`, `tests/unit/test_web.py`.
- **CI + README:** GitHub Actions runs lint + the full migration chain + the whole suite on
  every push/PR; README rewritten from the old scaffold stub to the finished project.

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
  tools/    cost_tools.py     # 16 agent tools + catalog_hint()
  agent/    graph.py state.py model.py prompts.py   # model.py = provider factory
  forecasting/  model.py service.py
  detection/    detector.py service.py
  budgets/      model.py store.py service.py
  analysis/     drivers.py                          # explain-why (cost drivers)
  allocation/   policy.py service.py                # v2: shared-cost allocation onto teams
  governance/   policy.py store.py service.py       # v2: policy engine (configurable, recommend-only)
  optimization/ model.py store.py service.py cli.py # v2: recommendation approval workflow
  knowledge/    corpus.py retriever.py service.py   # v2: RAG (qualitative only, no numbers)
  routing/      router.py                           # findings -> owner + recommendation
  surface/      report.py(HTML) web.py(FastAPI chat)
  eval/         dataset.py runner.py(tool-selection + faithfulness) numeric.py faithfulness.py
migrations/  0001_focus_schema 0002_budgets 0003_line_reconciliation 0004_blended_cost
             0005_recommendation_decisions 0006_snooze_until 0007_policies
             # 0003/0004/0006 idempotent, 0002/0005/0007 use checkfirst (0001 create_all
             # builds the current schema on fresh DBs)
```

## Registered queries (queries/registry.py)
Agent-facing: `total_spend, spend_by_service, spend_by_provider,
spend_by_charge_category, daily_spend, monthly_spend, spend_by_team,
spend_by_environment, month_over_month`.
Internal (agent_facing=False, power tools/features): `daily_spend_by_service,
charge_date_bounds, service_owners, service_catalog`.
`run_query(repo, name, params)` validates params + carries provenance; repo.execute()
runs prepared Core statements only (no string SQL).

## Agent tools (tools/cost_tools.py) — 16
One per agent-facing query, plus `forecast_spend, detect_anomalies, spend_vs_budget,
explain_change, route_findings, allocate_shared_spend, check_policies,
review_recommendations, search_knowledge`. `get_cost_tools(repo)` builds them;
`catalog_hint(repo)` injects the exact provider/service names into the system prompt at build
time. NOTE: `review_recommendations` is READ-ONLY (reports decision status, cannot approve —
only the human `mcca-review` CLI records decisions); `search_knowledge` is QUALITATIVE-ONLY
(concept/policy docs, never a source of a cost figure).

## v2 progress (post-v1)
- ✅ **contracted_cost** populated across all clouds — the FOCUS cost stack (list ≥ contracted
  ≥ billed ≥ effective) is now complete (`negotiated_discount` in the AWS generator; Azure/GCP
  use documented defaults). Proven: `test_messy_cases_seed.py`, normalize unit tests.
- ✅ **Attribution allocation policy** (`allocation/`) — derives fully-loaded team cost by
  splitting the shared/'unattributed' pool across teams (proportional/even/weighted). The
  warehouse is NOT mutated (raw stays honest); allocation is a deterministic calc over
  `spend_by_team` that reconciles to the pool exactly. Tool: `allocate_shared_spend`. Proven:
  `tests/unit/test_allocation.py`, `tests/integration/test_allocation_seed.py`.
- ✅ **Governance policy engine** (`governance/`) — declarative policies (untagged_limit,
  team_cap, denied_service) evaluated against the fixed queries, flagging VIOLATIONS with a
  recommended action. Recommend-only (never enforces). Tool: `check_policies`; shown in the
  dashboard as a "Policy compliance" panel. Proven: `tests/unit/test_governance.py`,
  `tests/integration/test_governance_seed.py`.
- ✅ **Optimization + approval workflow** (`optimization/`) — unifies routing findings +
  governance violations into live `Recommendation`s with a stable key; a human records a
  decision (approve/dismiss/snooze) via the `mcca-review` CLI, persisted in
  `recommendation_decisions` (migration `0005`). Recommendations are always recomputed
  (grounded); only the decision is stored. **A decision records intent only — nothing is
  executed** (stays read-only vs. infra). Agent tool `review_recommendations` is READ-ONLY
  (reports status, cannot approve). Proven: `tests/unit/test_optimization.py`,
  `tests/integration/test_optimization_seed.py`.
- ✅ **RAG knowledge layer** (`knowledge/`) — a curated qualitative corpus (concepts, cost-measure
  definitions, tagging/allocation/governance policy, forecasting caveats, the trust boundary)
  behind a swappable `Retriever` interface (default: dependency-free lexical/BM25-lite; a
  pgvector/embedding backend can swap in later). Tool `search_knowledge`. **STRICTLY qualitative
  — never a source of a cost figure**: a unit test asserts the corpus contains no dollar amounts,
  so RAG structurally cannot supply a number. Open NL→SQL is deliberately NOT built — the fixed
  query registry IS the semantic layer for numbers. Proven: `tests/unit/test_knowledge.py`.
- ✅ **v2 polish** — (a) governance policies are now **configurable/persisted** (`policies`
  table + `governance/store.py`, seeded by `mcca-seed`; `check_policies` reads the stored set);
  (b) **snooze has an expiry** (`snooze_until`; expired snoozes re-surface as PROPOSED); (c)
  **web approval buttons** — a "Recommendations & approvals" dashboard panel + `POST /decide`
  endpoint (records intent only); (d) **empty-answer retry** in the graph. Proven:
  `test_graph.py`, snooze/policy integration tests, `test_report.py`/`test_web.py`.
- **v2 roadmap complete.** Remaining out-of-scope by principle: optimization auto-actioning
  (permanent — read-only), and open-ended text-to-SQL (numbers stay behind the fixed queries).

## LLM provider — config-driven (agent/model.py)
`MCCA_LLM_PROVIDER` ∈ {google, ollama, anthropic, openai}. **Currently: ollama /
qwen3.5:9b** (local, free, unlimited, ~80 s/answer on a 6 GB GPU). Gemini
`gemini-2.5-flash-lite` kept as commented fallback in `.env` (fast but free tier is
20 req/day/model). Switching = flip two `.env` lines. Ollama at
`%LOCALAPPDATA%\Programs\Ollama`; model pulled (6.6 GB).

## Entry points / how to run
`docker compose up -d` → `uv run alembic upgrade head` → `uv run mcca-seed` (all 3
clouds, sets a $9k budget). Then: `uv run mcca-web` (chat UI at 127.0.0.1:8000),
`uv run mcca "question"` (CLI), `uv run mcca-report` (HTML), `uv run mcca-eval`
(tool-selection + prose faithfulness), `uv run mcca-eval-numeric` (deterministic
fixture-exact query check — no LLM), `uv run mcca-review` (human approval CLI:
list/approve/dismiss recommendations), `uv run mcca-simulate` (live near-real-time feed:
advances one day per tick, idempotent ingest + estimate→final + monitor; pair with
`mcca-web` at `?refresh=5`), `uv run pytest` (223 tests, +1 skipped live check).
`mcca-seed --cloud {aws,azure,gcp,all}`. NOTE: `uv run pytest` DROPS the seeded data
(integration fixtures drop_all at teardown) — re-seed afterward. Re-ingestion is now
idempotent (upsert), so `mcca-seed` can be re-run without double-counting. Both `mcca-web`
and `mcca` run the **runtime faithfulness guard** on every answer (see below).

## CI + README
- **CI**: `.github/workflows/ci.yml` runs on every push/PR — ruff (lint+format), the full
  `0001→0007` migration chain against a fresh Postgres service, and the whole test suite
  (unit + integration via a scripted model; no cloud creds or LLM key needed).
- **README.md**: rewritten from the old scaffold stub to reflect the finished project
  (what-it-is, trust boundary, setup, run commands, demo prompts, honest debt callout).

## Observability
Langfuse (`tracing.py`), config-driven via `MCCA_LANGFUSE_*`, off by default; enabled
in the dev `.env`. Applied at both graph.invoke sites (CLI + web) with flush on exit.

## Reliability work done (tool selection / grounding / narration)
- System prompt (`agent/prompts.py`): tool-selection rules (aggregates vs per-service),
  service-name disambiguation ("compute" per cloud), "ask if ambiguous".
- Sharpened tool descriptions (total_spend/monthly_spend = ALL-services totals).
- Dynamic **service catalog** injected into the prompt (exact names, never invent).
- Wide test vs qwen3.5:9b scored **11/11 tool selection**.
- **Forecast-narration guardrail** (`forecasting/model.py summarize_forecast`): the
  `forecast_spend` tool now hands the model the weekday/weekend direction as numbers, an
  explicit `interval_pct`, per-point weekday labels, and a `seasonality` caveat; the prompt
  forbids attributing a value to a holiday/calendar event. Neutralizes the confirmed
  weekday/weekend-inversion + hallucinated-holiday + interval-mislabel bug structurally.
- **Runtime faithfulness guard** (`eval/faithfulness.py check_messages/warning_line`): every
  `mcca-web` and `mcca` answer is checked; any dollar figure not traceable to a tool output
  is logged and surfaced to the user as a caveat (not silently trusted).

## KNOWN ISSUES / nits (all narration, never fabricated numbers)
The "numbers only from tools" guarantee HOLDS — every figure matches the deterministic
query/tool. Prior local-9B mis-narration issues are now mostly addressed:
- **Forecast weekday/weekend inversion + hallucinated "July 4th holiday" — GUARDED.** The
  `forecast_spend` output now states the direction, interval %, and a no-holiday seasonality
  caveat as data; the prompt forbids calendar-event stories (see Reliability work).
- **Forecast interval mislabel (said 90%, is 80%) — FIXED.** `interval_pct` is returned
  explicitly.
- **Fabricated dollar figures in prose — GUARDED at runtime.** The faithfulness guard flags
  any answer figure not traceable to a tool (web + CLI).
- **Empty final answer (tool ran, no narration) — FIXED.** `agent/graph.py` retries the
  model once with a nudge when it ends with neither a tool call nor any text.
- **`contracted_cost` — POPULATED.** The negotiated tier is modeled (AWS fully; Azure/GCP use
  documented defaults). The FOCUS list→contracted→billed→effective stack is now complete.

## Open v1 debts (require real data) — NOT done, do not mark done
These are unverifiable by construction until a real billing account exists. They are
genuine open debts to close **the instant real billing data is available**, not retired
goals — pretending otherwise breaks the core "provably correct numbers" bar.

1. **Reconcile-to-console (row 2 of the audit) — BLOCKED on real data.** No figure has been
   checked against a real Cost Explorer / Cost Management / BigQuery bill. What exists is
   internal consistency (`total == Σ categories`) and fixture-exact numeric faithfulness
   (`mcca-eval-numeric`, 9/9) — provably correct against *our synthetic ground truth*, which
   is NOT a real invoice. To close: ingest one real account's period and assert the warehouse
   totals match the console exactly.
2. **Full-normalization confirmation (row 1) — BLOCKED on real data.** RI/SP/credits/blended
   are now emitted, normalized, and fixture-tested end-to-end (`test_messy_cases_seed.py`).
   Still unconfirmed: that these figures and line-item mechanics match a real provider's
   CUR / Cost Management export. The synthetic RI/SP model is a faithful *shape*, not a
   validated *amount*. To close: diff normalized output against a real CUR.
3. **Live access-scoping check (row 7) — BLOCKED on real data.** Config, session-factory
   precedence, read-only `ce`-only client, and "no infra-mutation / no cloud SDK in
   agent+tools" are all tested (`test_access_scoping.py`). Unverified: that a real
   least-privilege IAM role / service principal authenticates and is denied writes at the
   provider. Marked with a visible skipped test. To close: run against a real reader role.

Also requires real accounts (structural, not a correctness debt):
- **Real ingestion clients**: AWS `client.py` is a real read-only boto3 factory but has never
  run against an account; Azure/GCP `client.py` are read-only-intent `NotImplementedError`
  stubs. Real path = swap the synthetic client for the real SDK client; normalize/loader/
  query layers are unchanged (proven by the synthetic providers sharing those exact paths).
- **CUR / line-item** granularity (resource-level, richer tags) — CE/Query/export aggregated
  shapes used instead.

## Optional polish
- ✅ **DONE** — Forecast-narration guardrail (see Reliability work).
- ✅ **DONE** — CI (GitHub Actions, runs on push/PR).
- ✅ **DONE** — README rewritten for the finished project.
- ✅ **DONE** — Runtime faithfulness guard (web + CLI).
- **NOT done (declined for now)** — `qwen3.5:4b` as a faster local option; qwen3.5:9b is the
  chosen tradeoff.
- **NOT done (minor)** — empty-final-answer retry; `contracted_cost` population (see nits).

## Deviations from the original plan
- **Tracing: Langfuse instead of LangSmith** (user decision).
- **Synthetic-only for now** — no real cloud accounts available; real-console reconciliation
  is deferred as an explicit **open v1 debt** (see above), NOT retired. It closes the instant
  real billing data is available.
- **"Surface" built as an interactive web chat UI** (`mcca-web`, FastAPI) in addition to
  the static HTML report — this is the user-facing "dashboard".

## Env quirks (Windows dev machine)
`uv` at `~/.local/bin` (not on PATH in fresh tool shells — prepend it). Docker Desktop
needs manual start. Python 3.14 via uv. `.env` holds real Gemini + Langfuse keys
(gitignored, verified NOT committed). Repo is PUBLIC on GitHub — never commit `.env`.
