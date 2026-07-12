# Multi-Cloud Cost Analyzer (MCCA)

[![CI](https://github.com/goktugdsert/Finops-multiple-cloud-cost-analyzer-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/goktugdsert/Finops-multiple-cloud-cost-analyzer-agent/actions/workflows/ci.yml)

A read-only, multi-cloud **FinOps agent** (LangChain / LangGraph) that normalizes AWS,
Azure, and GCP billing into one **FOCUS-schema** warehouse, then measures, attributes,
detects, explains, forecasts, and tracks cloud spend against budgets — routing findings to
an owner with a recommended action. It **recommends only; it never touches infrastructure.**

> **Core principle (non-negotiable):** the LLM orchestrates and explains but **never
> produces a cost figure of its own.** Every number comes from a deterministic tool — a
> validated SQL query or a calculation. If a number can't be traced to a query, it isn't
> shown. This is enforced *structurally* (see [Trust boundary](#trust-boundary)), not by a
> prompt.

## Status

**v1 is feature-complete and validated on synthetic data**, plus a v2 layer (allocation,
governance, an approval workflow, and a qualitative RAG knowledge base — see
[Beyond the loop](#beyond-the-loop-v2)). All three clouds, the full FinOps loop, both pillars
(unified visibility + predictive budgeting), an interactive dashboard, evals, and Langfuse
tracing. **206 tests pass** (+1 intentionally skipped live-credential check).

**Honest scope:** there are no real cloud accounts — the agent runs on a deterministic
**synthetic** dataset that emits each cloud's native billing shape. "Validated" means
*provably correct against synthetic ground truth*, **not** reconciled to a real invoice.
Three items remain open debts that require real billing data and are explicitly **not**
done: real-console reconciliation, real-CUR confirmation of RI/SP/credit/blended handling,
and the live least-privilege access-scoping check. See
[CLAUDE.md → Open v1 debts](CLAUDE.md).

## What it does — the FinOps loop

```
measure → attribute → detect → explain → forecast → track-vs-budget → route-to-owner
```

- **Measure** spend across AWS/Azure/GCP through a fixed set of validated queries.
- **Attribute** it to team / service / environment / owner (untagged spend shows honestly
  as `unattributed`).
- **Detect** both spending spikes and steady structural waste.
- **Explain** *why* spend changed (per-service driver decomposition).
- **Forecast** future daily spend (SARIMAX, with an uncertainty band always shown).
- **Track** month-to-date + forecast against a stored budget.
- **Route** findings to an owner with a recommended action (recommend-only).

## Beyond the loop (v2)

Built on the same trust boundary — every number still comes from a deterministic query:

- **Cost allocation** — spread the shared/`unattributed` pool onto teams for a *fully-loaded*
  cost (proportional / even / weighted). A derived view; the warehouse is never rewritten and
  shares reconcile to the pool exactly. Tool: `allocate_shared_spend`.
- **Governance policy engine** — declarative policies (untagged-spend limits, per-team caps,
  restricted services) evaluated against the warehouse, flagging violations with a recommended
  action. Recommend-only, never enforced. Tool: `check_policies`.
- **Approval workflow** — findings + violations become reviewable recommendations; a human
  records a decision (approve / dismiss / snooze) via `uv run mcca-review`, persisted per
  recommendation. **A decision records intent only — nothing is executed.** The agent can
  *report* status (`review_recommendations`) but cannot approve.
- **Knowledge base (RAG)** — a curated, qualitative FinOps knowledge base for concept/policy
  questions (`search_knowledge`). **Strictly qualitative — never a source of a cost figure**
  (a test asserts the corpus contains no dollar amounts).

Permanently out of scope by principle: auto-actioning against infrastructure (read-only), and
open-ended text-to-SQL (numbers always stay behind the fixed, validated queries).

## Trust boundary

```
ingestion/{aws,azure,gcp} ──┐
                            ├──► warehouse (FOCUS schema, behind a repository interface)
queries (fixed, validated) ─┘            ▲
   ▲                                      │
tools (run queries + calculations only) ──┘
   ▲
agent (LangGraph loop) ──► tools ONLY
```

- The warehouse repository has **no string-SQL entry point** — only prepared, registered
  statements run. The agent chooses a query *name* and parameters; it never writes SQL.
- `agent/` and `tools/` import **no cloud SDK** (`boto3`/azure/google) — the reasoning
  layer literally cannot reach a cloud API or mutate anything.
- A **numeric-faithfulness** check re-derives every query answer independently and asserts
  exact agreement, and a **prose-faithfulness** guard flags any dollar figure in an answer
  that traces to no tool output. (`uv run mcca-eval-numeric`.)

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — manages Python (3.11+) and dependencies
- Docker — local Postgres warehouse
- *(optional)* [Ollama](https://ollama.com/) for a free local LLM, or a Google/OpenAI/
  Anthropic key — only needed to actually chat with the agent; **not** needed for setup,
  seeding, the report, or the test suite

## Setup

```bash
cp .env.example .env            # then edit; .env is gitignored — never commit it
uv sync                          # create venv, install deps
docker compose up -d             # start local Postgres (pinned 16.4)
uv run alembic upgrade head      # create the FOCUS schema
uv run mcca-seed                 # load ~9 months of synthetic AWS+Azure+GCP data + a budget
```

`mcca-seed --cloud {aws,azure,gcp,all}` seeds a subset. Re-ingestion is idempotent
(upsert on natural billing-line identity), so re-running never double-counts.

## Running it

```bash
uv run mcca-web            # interactive chat UI + dashboard at http://127.0.0.1:8000
uv run mcca "How much did we spend in total from 2026-01-01 to 2026-04-01?"
uv run mcca-report        # generate a self-contained HTML dashboard
uv run mcca-review        # review recommendations; approve/dismiss/snooze (human decisions)
uv run mcca-eval          # agent eval: tool selection + prose numeric faithfulness (needs an LLM)
uv run mcca-eval-numeric  # deterministic: every fixed query returns fixture-exact figures (no LLM)
```

### Demo prompts

- `What were the top 3 services by cost from 2026-01-01 to 2026-07-01?`
- `Which cloud provider costs the most this year?`
- `Are we on track against our budget for June 2026?`
- `Why did spend change from May to June 2026?`
- `Forecast our daily spend for the next 30 days.`
- `What cost findings should we act on, and who owns them?`
- `What's each team's fully-loaded cost including shared spend, Jan–Apr 2026?`
- `Are we breaching any cost governance policies this year?`
- `Explain the difference between blended and unblended cost.`

## LLM provider (config-driven, swappable)

The agent's model is chosen by `MCCA_LLM_PROVIDER` ∈ `{ollama, google, openai, anthropic}`
(and `MCCA_AGENT_MODEL`). The graph and tools are provider-agnostic — switching is two
lines in `.env`. Free options: **ollama** (local, unlimited) or **google** (free tier).
The LLM is a reasoning/orchestration engine only; it is never a source of figures.

## Testing & CI

```bash
uv run pytest                        # full suite (integration self-skips if Postgres is down)
uv run pytest -m "not integration"   # unit only (no DB needed)
uv run ruff check . && uv run ruff format --check .
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs ruff, applies the full
migration chain against a fresh Postgres, and runs the entire suite (unit + integration,
via a scripted model — no cloud creds or LLM key) on every push and PR.

## More

- **Full scope, principles, as-built status, and open debts:** [CLAUDE.md](CLAUDE.md)
- **Data model:** FOCUS (FinOps Open Cost & Usage Specification), Postgres in v1 behind a
  `WarehouseRepository` interface so the store can be swapped without touching agent logic.
