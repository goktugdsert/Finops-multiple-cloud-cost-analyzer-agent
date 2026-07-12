"""LangChain tools wrapping the fixed query set — the agent's ONLY numeric source.

Each registered query becomes a StructuredTool whose arguments mirror the query's declared
parameters. A tool call runs `run_query` and returns the JSON-safe `QueryResult` (query
name + validated params + rows), so every figure the agent sees is traceable to a query.
The agent has no other path to a number: it cannot reach the warehouse, SQL, or ingestion.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field, create_model

from mcca.allocation.service import allocate_team_spend
from mcca.analysis.drivers import explain_change
from mcca.budgets.service import spend_vs_budget
from mcca.detection.service import detect
from mcca.forecasting.model import summarize_forecast
from mcca.forecasting.service import forecast_daily_spend
from mcca.governance.service import evaluate_policies
from mcca.knowledge.service import search_knowledge
from mcca.optimization.service import review_recommendations
from mcca.queries.registry import (
    COST_METRICS,
    QueryDefinition,
    list_queries,
    run_query,
)
from mcca.routing.router import route

if False:  # typing-only; avoids importing the warehouse impl into the tools layer
    from mcca.warehouse.repository import WarehouseRepository


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _serialize(result: Any) -> dict[str, Any]:
    return {
        "query": result.name,
        "params": {k: _json_safe(v) for k, v in result.params.items()},
        "rows": [{k: _json_safe(v) for k, v in row.items()} for row in result.rows],
    }


def _args_model(definition: QueryDefinition) -> type:
    """Build a pydantic args schema mirroring the query's parameter contract."""
    fields: dict[str, tuple] = {}
    for param in definition.params:
        if param.name in ("start", "end"):
            if param.required:
                fields[param.name] = (date, Field(..., description="ISO date, YYYY-MM-DD."))
            else:
                fields[param.name] = (date | None, Field(None))
        elif param.name == "metric":
            fields[param.name] = (
                str | None,
                Field(param.default, description=f"Cost measure, one of {list(COST_METRICS)}."),
            )
        elif param.name == "limit":
            fields[param.name] = (int | None, Field(None, description="Max rows to return."))
        else:
            fields[param.name] = (
                str | None,
                Field(None, description=f"Optional {param.name} filter."),
            )
    return create_model(f"{definition.name}_args", **fields)


def _make_tool(definition: QueryDefinition, repo: WarehouseRepository) -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        params = {k: v for k, v in kwargs.items() if v is not None}
        return _serialize(run_query(repo, definition.name, params))

    return StructuredTool.from_function(
        func=_run,
        name=definition.name,
        description=definition.description,
        args_schema=_args_model(definition),
    )


def _serialize_forecast(forecast: Any) -> dict[str, Any]:
    # Deterministic narration guards so the model can't invert the weekly pattern, invent a
    # holiday, or mislabel the interval — it reads direction/seasonality/interval from here.
    narration = summarize_forecast(forecast)
    return {
        "model": forecast.model,
        "metric": forecast.metric,
        "interval": forecast.interval,
        "interval_pct": narration.interval_pct,
        "seasonality": narration.seasonality,
        "summary": {
            "weekday_mean": str(narration.weekday_mean),
            "weekend_mean": str(narration.weekend_mean),
            "higher": narration.higher,
        },
        "horizon": forecast.horizon,
        "history_start": _json_safe(forecast.history_start),
        "history_end": _json_safe(forecast.history_end),
        "history_points": forecast.history_points,
        "points": [
            {
                "date": p.date.isoformat(),
                "weekday": p.date.strftime("%a"),
                "is_weekend": p.date.weekday() >= 5,
                "yhat": str(p.yhat),
                "lower": str(p.lower),
                "upper": str(p.upper),
            }
            for p in forecast.points
        ],
    }


def _forecast_args() -> type:
    return create_model(
        "forecast_spend_args",
        start=(date, Field(..., description="History start, ISO date YYYY-MM-DD.")),
        end=(date, Field(..., description="History end (exclusive), ISO date YYYY-MM-DD.")),
        horizon=(int | None, Field(30, description="Days to forecast ahead.")),
        interval=(float | None, Field(0.8, description="Prediction interval width, e.g. 0.8=80%.")),
        metric=(str | None, Field("billed_cost", description=f"One of {list(COST_METRICS)}.")),
        service=(str | None, Field(None, description="Optional single service to forecast.")),
    )


def _make_forecast_tool(repo: WarehouseRepository) -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        forecast = forecast_daily_spend(
            repo,
            kwargs["start"],
            kwargs["end"],
            horizon=kwargs.get("horizon") or 30,
            interval=kwargs.get("interval") or 0.8,
            metric=kwargs.get("metric") or "billed_cost",
            service=kwargs.get("service"),
        )
        return _serialize_forecast(forecast)

    return StructuredTool.from_function(
        func=_run,
        name="forecast_spend",
        description=(
            "Forecast future daily spend with an uncertainty (prediction) interval, using "
            "historical daily spend over [start, end). Returns lower/upper bounds, an "
            "explicit `interval_pct`, a `seasonality` note (what the model does and does NOT "
            "capture), and a `summary` giving weekday vs weekend mean spend and which is "
            "`higher` — read direction and interval from these, do not infer them."
        ),
        args_schema=_forecast_args(),
    )


def _serialize_detection(report: Any) -> dict[str, Any]:
    return {
        "window": report.window,
        "z": report.z,
        "spikes": [
            {
                "date": s.date.isoformat(),
                "service": s.service,
                "amount": str(s.amount),
                "baseline": str(s.baseline),
                "ratio": round(s.ratio, 2),
            }
            for s in report.spikes
        ],
        "steady_costs": [
            {
                "service": c.service,
                "mean_daily": str(c.mean_daily),
                "monthly_estimate": str(c.monthly_estimate),
                "cov": c.cov,
            }
            for c in report.steady_costs
        ],
    }


def _detection_args() -> type:
    return create_model(
        "detect_anomalies_args",
        start=(date, Field(..., description="Window start, ISO date YYYY-MM-DD.")),
        end=(date, Field(..., description="Window end (exclusive), ISO date YYYY-MM-DD.")),
        metric=(str | None, Field("billed_cost", description=f"One of {list(COST_METRICS)}.")),
        window=(int | None, Field(14, description="Trailing baseline window in days.")),
        z=(float | None, Field(3.0, description="Z-score threshold for a spike.")),
    )


def _make_detection_tool(repo: WarehouseRepository) -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        report = detect(
            repo,
            kwargs["start"],
            kwargs["end"],
            metric=kwargs.get("metric") or "billed_cost",
            window=kwargs.get("window") or 14,
            z=kwargs.get("z") or 3.0,
        )
        return _serialize_detection(report)

    return StructuredTool.from_function(
        func=_run,
        name="detect_anomalies",
        description=(
            "Detect cost anomalies over [start, end): spending SPIKES (days far above a "
            "service's trailing baseline) and STEADY structural spend (flat, persistent "
            "cost worth an efficiency review)."
        ),
        args_schema=_detection_args(),
    )


def _make_budget_tool(repo: WarehouseRepository) -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        status = spend_vs_budget(
            repo, kwargs["month"], metric=kwargs.get("metric") or "billed_cost"
        )
        if status is None:
            return {"status": "NO_BUDGET", "message": "No budget configured for this scope."}
        return {
            "month": status.month.isoformat(),
            "scope": status.scope,
            "status": status.status,
            "budget_amount": str(status.budget_amount),
            "actual_so_far": str(status.actual),
            "forecast_remaining": str(status.forecast_mid),
            "projected_month_end": str(status.projected),
            "projected_range": [str(status.projected_lo), str(status.projected_hi)],
            "variance": str(status.variance),
            "variance_pct": round(status.variance_pct, 1),
        }

    return StructuredTool.from_function(
        func=_run,
        name="spend_vs_budget",
        description=(
            "Track spend against the monthly budget for a given month: month-to-date "
            "actuals plus a forecast of the rest of the month, projected against the "
            "budget, with an ON_TRACK / AT_RISK / OVER status. Pass any date in the month."
        ),
        args_schema=create_model(
            "spend_vs_budget_args",
            month=(date, Field(..., description="Any date in the target month (YYYY-MM-DD).")),
            metric=(str | None, Field("billed_cost", description=f"One of {list(COST_METRICS)}.")),
        ),
    )


def _make_explain_tool(repo: WarehouseRepository) -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        exp = explain_change(
            repo,
            kwargs["start"],
            kwargs["end"],
            metric=kwargs.get("metric") or "billed_cost",
            top_n=kwargs.get("top_n") or 5,
        )
        return {
            "period": [exp.current_start.isoformat(), exp.current_end.isoformat()],
            "prior_period": [exp.prior_start.isoformat(), exp.prior_end.isoformat()],
            "current_total": str(exp.current_total),
            "prior_total": str(exp.prior_total),
            "total_delta": str(exp.total_delta),
            "drivers": [
                {
                    "service": d.service,
                    "current": str(d.current),
                    "prior": str(d.prior),
                    "delta": str(d.delta),
                }
                for d in exp.drivers
            ],
        }

    return StructuredTool.from_function(
        func=_run,
        name="explain_change",
        description=(
            "Explain why spend changed: decompose the change for [start, end) versus the "
            "equal-length prior period into the per-service drivers that moved most."
        ),
        args_schema=create_model(
            "explain_change_args",
            start=(date, Field(..., description="Period start, ISO date YYYY-MM-DD.")),
            end=(date, Field(..., description="Period end (exclusive), ISO date YYYY-MM-DD.")),
            metric=(str | None, Field("billed_cost", description=f"One of {list(COST_METRICS)}.")),
            top_n=(int | None, Field(5, description="How many top drivers to return.")),
        ),
    )


def _make_routing_tool(repo: WarehouseRepository) -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        report = route(
            repo, kwargs["start"], kwargs["end"], budget_month=kwargs.get("budget_month")
        )
        return {
            "findings": [
                {
                    "kind": f.kind,
                    "severity": f.severity,
                    "service": f.service,
                    "team": f.team,
                    "owner": f.owner,
                    "amount": str(f.amount),
                    "summary": f.summary,
                    "recommendation": f.recommendation,
                }
                for f in report.findings
            ]
        }

    return StructuredTool.from_function(
        func=_run,
        name="route_findings",
        description=(
            "Produce a prioritized list of cost findings (spikes, steady waste, budget "
            "breaches) over [start, end), each routed to an owner with a RECOMMENDED "
            "action. Read-only — recommends only, never executes. Pass budget_month to "
            "include budget breaches."
        ),
        args_schema=create_model(
            "route_findings_args",
            start=(date, Field(..., description="Window start, ISO date YYYY-MM-DD.")),
            end=(date, Field(..., description="Window end (exclusive), ISO date YYYY-MM-DD.")),
            budget_month=(
                date | None,
                Field(None, description="Any date in the month to check against budget."),
            ),
        ),
    )


def _make_allocation_tool(repo: WarehouseRepository) -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        result = allocate_team_spend(
            repo,
            kwargs["start"],
            kwargs["end"],
            method=kwargs.get("method") or "proportional",
            metric=kwargs.get("metric") or "billed_cost",
            weights=kwargs.get("weights"),
        )
        return {
            "method": result.method,
            "shared_pool": str(result.shared_pool),
            "unallocated": str(result.unallocated),
            "teams": [
                {
                    "team": t.team,
                    "direct": str(t.direct),
                    "allocated": str(t.allocated),
                    "total": str(t.total),
                }
                for t in result.teams
            ],
        }

    return StructuredTool.from_function(
        func=_run,
        name="allocate_shared_spend",
        description=(
            "Compute fully-loaded team cost by allocating shared/'unattributed' spend across "
            "teams over [start, end). Returns each team's direct spend, its allocated share of "
            "the shared pool, and the total. `method`: proportional (default, by direct spend), "
            "even, or weighted (requires `weights`, a team->number map). Use this for 'including "
            "shared costs' / 'fully-loaded' team questions; `spend_by_team` alone is direct "
            "(tagged) spend only."
        ),
        args_schema=create_model(
            "allocate_shared_spend_args",
            start=(date, Field(..., description="Window start, ISO date YYYY-MM-DD.")),
            end=(date, Field(..., description="Window end (exclusive), ISO date YYYY-MM-DD.")),
            method=(
                str | None,
                Field("proportional", description="proportional | even | weighted."),
            ),
            metric=(str | None, Field("billed_cost", description=f"One of {list(COST_METRICS)}.")),
            weights=(
                dict[str, float] | None,
                Field(None, description='For method=weighted: team->weight, e.g. {"platform": 3}.'),
            ),
        ),
    )


def _make_governance_tool(repo: WarehouseRepository) -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        violations = evaluate_policies(
            repo, kwargs["start"], kwargs["end"], metric=kwargs.get("metric") or "billed_cost"
        )
        return {
            "violations": [
                {
                    "policy_id": v.policy_id,
                    "kind": v.kind,
                    "severity": v.severity,
                    "scope": v.scope,
                    "observed": str(v.observed),
                    "threshold": str(v.threshold),
                    "summary": v.summary,
                    "recommendation": v.recommendation,
                }
                for v in violations
            ]
        }

    return StructuredTool.from_function(
        func=_run,
        name="check_policies",
        description=(
            "Evaluate spend over [start, end) against the governance policy set — untagged-spend "
            "limits, per-team caps, and restricted services — and return policy VIOLATIONS, each "
            "with a recommended action. Use for compliance / 'are we following our cost policies' "
            "/ 'any policy violations' questions. Recommend-only: nothing is enforced."
        ),
        args_schema=create_model(
            "check_policies_args",
            start=(date, Field(..., description="Window start, ISO date YYYY-MM-DD.")),
            end=(date, Field(..., description="Window end (exclusive), ISO date YYYY-MM-DD.")),
            metric=(str | None, Field("billed_cost", description=f"One of {list(COST_METRICS)}.")),
        ),
    )


def _make_review_tool(repo: WarehouseRepository) -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        result = review_recommendations(repo, kwargs["start"], kwargs["end"])
        return {
            "counts": result.counts,
            "recommendations": [
                {
                    "key": r.key,
                    "source": r.source,
                    "kind": r.kind,
                    "severity": r.severity,
                    "scope": r.scope,
                    "amount": None if r.amount is None else str(r.amount),
                    "summary": r.summary,
                    "action": r.action,
                    "status": r.status,
                    "decided_by": r.decided_by,
                }
                for r in result.recommendations
            ],
        }

    return StructuredTool.from_function(
        func=_run,
        name="review_recommendations",
        description=(
            "List the current cost recommendations (from findings + policy violations) over "
            "[start, end), each with its human decision STATUS (PROPOSED / APPROVED / DISMISSED "
            "/ SNOOZED) and a status summary. READ-ONLY: report status; you cannot approve or "
            "change decisions — a human records those. Use for 'what's approved / pending / "
            "dismissed' and 'what should we act on' questions."
        ),
        args_schema=create_model(
            "review_recommendations_args",
            start=(date, Field(..., description="Window start, ISO date YYYY-MM-DD.")),
            end=(date, Field(..., description="Window end (exclusive), ISO date YYYY-MM-DD.")),
        ),
    )


def _make_knowledge_tool() -> BaseTool:
    def _run(**kwargs: Any) -> dict[str, Any]:
        passages = search_knowledge(kwargs["query"], k=kwargs.get("k") or 3)
        return {
            "passages": [
                {"title": p.title, "source": p.source, "text": p.text, "score": p.score}
                for p in passages
            ]
        }

    return StructuredTool.from_function(
        func=_run,
        name="search_knowledge",
        description=(
            "Search the qualitative FinOps knowledge base (concept definitions, cost-measure "
            "meanings, tagging/allocation/governance policy, forecasting caveats, the trust "
            "boundary) and return relevant passages. Use for conceptual questions — 'what is', "
            "'how does', 'explain', 'define', 'why', 'what is our policy on'. It is NOT a source "
            "of cost figures: it returns only qualitative documentation, so for any dollar "
            "amount use the numeric query tools, never this."
        ),
        args_schema=create_model(
            "search_knowledge_args",
            query=(str, Field(..., description="The concept/definition/policy question.")),
            k=(int | None, Field(3, description="Max passages to return.")),
        ),
    )


def catalog_hint(repo: WarehouseRepository) -> str:
    """A compact list of the exact provider/service names in the warehouse, for the prompt.

    Grounds the agent so it never invents a service name (and knows to disambiguate a
    generic term across clouds). Returns "" if the warehouse is empty/unreadable — it must
    never break agent construction.
    """
    try:
        rows = run_query(repo, "service_catalog", {}).rows
    except Exception:  # noqa: BLE001 - a missing catalog just means no hint
        return ""
    by_provider: dict[str, list[str]] = {}
    for row in rows:
        provider, service = row.get("provider_name"), row.get("service_name")
        if provider and service:
            by_provider.setdefault(provider, []).append(service)
    if not by_provider:
        return ""
    lines = ["Services currently in the warehouse (use these EXACT names; never invent one):"]
    lines += [f"- {p}: {', '.join(sorted(by_provider[p]))}" for p in sorted(by_provider)]
    return "\n".join(lines)


def get_cost_tools(repo: WarehouseRepository) -> list[BaseTool]:
    """Build the agent's tools: queries + forecast + detection + budget + explain + route."""
    tools = [_make_tool(d, repo) for d in list_queries() if d.agent_facing]
    tools.append(_make_forecast_tool(repo))
    tools.append(_make_detection_tool(repo))
    tools.append(_make_budget_tool(repo))
    tools.append(_make_explain_tool(repo))
    tools.append(_make_routing_tool(repo))
    tools.append(_make_allocation_tool(repo))
    tools.append(_make_governance_tool(repo))
    tools.append(_make_review_tool(repo))
    tools.append(_make_knowledge_tool())
    return tools
