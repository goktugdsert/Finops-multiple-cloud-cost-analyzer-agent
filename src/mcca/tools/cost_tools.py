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

from mcca.analysis.drivers import explain_change
from mcca.budgets.service import spend_vs_budget
from mcca.detection.service import detect
from mcca.forecasting.service import forecast_daily_spend
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
    return {
        "model": forecast.model,
        "metric": forecast.metric,
        "interval": forecast.interval,
        "horizon": forecast.horizon,
        "history_start": _json_safe(forecast.history_start),
        "history_end": _json_safe(forecast.history_end),
        "history_points": forecast.history_points,
        "points": [
            {
                "date": p.date.isoformat(),
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
            "historical daily spend over [start, end). Always returns lower/upper bounds."
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


def get_cost_tools(repo: WarehouseRepository) -> list[BaseTool]:
    """Build the agent's tools: queries + forecast + detection + budget + explain + route."""
    tools = [_make_tool(d, repo) for d in list_queries() if d.agent_facing]
    tools.append(_make_forecast_tool(repo))
    tools.append(_make_detection_tool(repo))
    tools.append(_make_budget_tool(repo))
    tools.append(_make_explain_tool(repo))
    tools.append(_make_routing_tool(repo))
    return tools
