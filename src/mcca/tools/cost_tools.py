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

from mcca.forecasting.service import forecast_daily_spend
from mcca.queries.registry import (
    COST_METRICS,
    QueryDefinition,
    list_queries,
    run_query,
)

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


def get_cost_tools(repo: WarehouseRepository) -> list[BaseTool]:
    """Build the agent's tools: one per registered query, plus the forecast tool."""
    tools = [_make_tool(definition, repo) for definition in list_queries()]
    tools.append(_make_forecast_tool(repo))
    return tools
