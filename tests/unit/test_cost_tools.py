"""The cost tools wrap the query set correctly and return JSON-safe, traceable results."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from mcca.tools.cost_tools import get_cost_tools

EXPECTED_TOOL_NAMES = {
    "total_spend",
    "spend_by_service",
    "spend_by_provider",
    "spend_by_charge_category",
    "daily_spend",
    "monthly_spend",
    "spend_by_team",
    "spend_by_environment",
    "month_over_month",
    "forecast_spend",
    "detect_anomalies",
    "spend_vs_budget",
    "explain_change",
    "route_findings",
    "allocate_shared_spend",
    "check_policies",
    "review_recommendations",
    "search_knowledge",
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


def test_forecast_tool_includes_narration_guards() -> None:
    from datetime import date, timedelta

    rows = [
        {"day": date(2026, 1, 1) + timedelta(days=i), "amount": Decimal(str(100 + i))}
        for i in range(40)
    ]
    tool = _tool(get_cost_tools(FakeRepo(rows)), "forecast_spend")
    out = tool.invoke({"start": "2026-01-01", "end": "2026-02-10", "horizon": 14})

    # Explicit interval + seasonality caveat so the model can't mislabel or invent a holiday.
    assert out["interval_pct"] == 80
    assert "holiday" in out["seasonality"].lower()
    # Weekday/weekend direction is handed over as data, not left to inference.
    assert set(out["summary"]) == {"weekday_mean", "weekend_mean", "higher"}
    assert out["summary"]["higher"] in {"weekdays", "weekends", "about the same"}
    # Every point is labeled with its weekday so the pattern can't be reversed.
    for p in out["points"]:
        assert p["weekday"] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
        assert isinstance(p["is_weekend"], bool)


def test_tool_returns_json_safe_result_with_provenance() -> None:
    repo = FakeRepo([{"billed_cost": Decimal("123.45"), "effective_cost": Decimal("100.00")}])
    tool = _tool(get_cost_tools(repo), "total_spend")

    out = tool.invoke({"start": "2026-03-01", "end": "2026-05-01"})

    assert out["query"] == "total_spend"
    assert out["params"]["start"] == "2026-03-01"  # dates serialized to ISO strings
    assert out["rows"][0]["billed_cost"] == "123.45"  # Decimal serialized to str
    assert isinstance(out["rows"][0]["billed_cost"], str)
    assert repo.statement is not None


def test_allocation_tool_returns_fully_loaded_team_cost() -> None:
    # spend_by_team rows: two real teams + a shared 'unattributed' pool of $100.
    rows = [
        {"x_team": "platform", "amount": Decimal("300")},
        {"x_team": "data", "amount": Decimal("100")},
        {"x_team": "unattributed", "amount": Decimal("100")},
    ]
    tool = _tool(get_cost_tools(FakeRepo(rows)), "allocate_shared_spend")
    out = tool.invoke({"start": "2026-01-01", "end": "2026-04-01"})

    assert out["method"] == "proportional"
    assert out["shared_pool"] == "100.00"
    assert out["unallocated"] == "0.00"
    by_team = {t["team"]: t for t in out["teams"]}
    # Proportional: platform gets 3/4 of the pool, data 1/4.
    assert by_team["platform"]["allocated"] == "75.00"
    assert by_team["data"]["allocated"] == "25.00"
    assert by_team["platform"]["total"] == "375.00"
    # Allocated shares reconcile to the pool exactly (nothing lost or invented).
    allocated = sum(Decimal(t["allocated"]) for t in out["teams"])
    assert allocated == Decimal("100.00")


def test_allocation_tool_weighted_method_uses_supplied_weights() -> None:
    rows = [
        {"x_team": "platform", "amount": Decimal("300")},
        {"x_team": "data", "amount": Decimal("100")},
        {"x_team": "unattributed", "amount": Decimal("100")},
    ]
    tool = _tool(get_cost_tools(FakeRepo(rows)), "allocate_shared_spend")
    out = tool.invoke(
        {
            "start": "2026-01-01",
            "end": "2026-04-01",
            "method": "weighted",
            "weights": {"platform": 1, "data": 3},  # data gets 3/4 despite less direct spend
        }
    )
    by_team = {t["team"]: t for t in out["teams"]}
    assert by_team["data"]["allocated"] == "75.00"
    assert by_team["platform"]["allocated"] == "25.00"
    assert out["unallocated"] == "0.00"  # weights supplied -> fully allocated, not stranded


def test_governance_tool_flags_policy_violations() -> None:
    # Rows carry both x_team and service_name so the default policies can evaluate.
    rows = [
        {"x_team": "platform", "service_name": "Amazon EC2", "amount": Decimal("200000")},
        {"x_team": "unattributed", "service_name": "Tax", "amount": Decimal("1000")},
    ]
    tool = _tool(get_cost_tools(FakeRepo(rows)), "check_policies")
    out = tool.invoke({"start": "2026-01-01", "end": "2026-04-01"})

    # platform ($200k) breaches the default $100k team cap.
    caps = [v for v in out["violations"] if v["kind"] == "team_cap"]
    assert caps and caps[0]["scope"] == "platform"
    assert caps[0]["severity"] == "MEDIUM"
    assert "recommendation" in caps[0]


def test_knowledge_tool_returns_qualitative_passages() -> None:
    # search_knowledge needs no repo/DB — it's over the curated corpus.
    tool = _tool(get_cost_tools(FakeRepo([])), "search_knowledge")
    out = tool.invoke({"query": "explain blended vs unblended cost"})
    assert out["passages"], "expected at least one relevant passage"
    top = out["passages"][0]
    assert "cost" in top["text"].lower()
    # A knowledge passage never carries a dollar figure (RAG is not a number source).
    assert "$" not in top["text"]


def test_tool_rejects_invalid_metric() -> None:
    tool = _tool(get_cost_tools(FakeRepo([])), "spend_by_service")
    with pytest.raises(Exception, match="Invalid value"):
        tool.invoke({"start": "2026-03-01", "end": "2026-05-01", "metric": "hacks"})
