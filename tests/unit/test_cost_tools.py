"""The cost tools wrap the query set correctly and return JSON-safe, traceable results."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from mcca.tools.cost_tools import get_cost_tools

EXPECTED_TOOL_NAMES = {
    "total_spend",
    "spend_by_service",
    "spend_by_charge_category",
    "daily_spend",
    "monthly_spend",
    "spend_by_team",
    "spend_by_environment",
    "month_over_month",
    "forecast_spend",
}


class FakeRepo:
    """Repository whose execute() returns canned rows, capturing the statement."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.statement: Any = None

    def execute(self, statement: Any) -> list[dict[str, Any]]:
        self.statement = statement
        return self.rows

    def create_schema(self) -> None: ...
    def insert_records(self, records: Any) -> int: ...
    def fetch_all(self) -> list[dict[str, Any]]: ...


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


def test_one_tool_per_query_plus_forecast() -> None:
    tools = get_cost_tools(FakeRepo([]))
    assert {t.name for t in tools} == EXPECTED_TOOL_NAMES
    assert all(t.description for t in tools)


def test_forecast_tool_returns_bounded_points() -> None:
    from datetime import date, timedelta

    rows = [
        {"day": date(2026, 1, 1) + timedelta(days=i), "amount": Decimal(str(100 + i))}
        for i in range(40)
    ]
    tool = _tool(get_cost_tools(FakeRepo(rows)), "forecast_spend")
    out = tool.invoke({"start": "2026-01-01", "end": "2026-02-10", "horizon": 14})

    assert out["horizon"] == 14
    assert len(out["points"]) == 14
    for p in out["points"]:
        assert float(p["lower"]) <= float(p["yhat"]) <= float(p["upper"])


def test_tool_returns_json_safe_result_with_provenance() -> None:
    repo = FakeRepo([{"billed_cost": Decimal("123.45"), "effective_cost": Decimal("100.00")}])
    tool = _tool(get_cost_tools(repo), "total_spend")

    out = tool.invoke({"start": "2026-03-01", "end": "2026-05-01"})

    assert out["query"] == "total_spend"
    assert out["params"]["start"] == "2026-03-01"  # dates serialized to ISO strings
    assert out["rows"][0]["billed_cost"] == "123.45"  # Decimal serialized to str
    assert isinstance(out["rows"][0]["billed_cost"], str)
    assert repo.statement is not None


def test_tool_rejects_invalid_metric() -> None:
    tool = _tool(get_cost_tools(FakeRepo([])), "spend_by_service")
    with pytest.raises(Exception, match="Invalid value"):
        tool.invoke({"start": "2026-03-01", "end": "2026-05-01", "metric": "hacks"})
