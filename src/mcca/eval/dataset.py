"""Curated eval cases: a question and the tool(s) a correct agent should call.

Dates are explicit so the agent can answer without a clarifying round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    name: str
    question: str
    expected_tools: frozenset[str] = field(default_factory=frozenset)
    require_tool_use: bool = True


EVAL_CASES: list[EvalCase] = [
    EvalCase(
        "total_spend",
        "How much did we spend in total from 2026-01-01 to 2026-04-01?",
        frozenset({"total_spend"}),
    ),
    EvalCase(
        "spend_by_service",
        "What were the top 3 services by cost between 2026-01-01 and 2026-04-01?",
        frozenset({"spend_by_service"}),
    ),
    EvalCase(
        "month_over_month",
        "Show the month-over-month spend trend from 2026-01-01 to 2026-04-01.",
        frozenset({"month_over_month"}),
    ),
    EvalCase(
        "spend_by_charge_category",
        "Break spend down by charge category for 2026-01-01 to 2026-04-01.",
        frozenset({"spend_by_charge_category"}),
    ),
    EvalCase(
        "forecast_spend",
        "Forecast our daily spend for the next 30 days using history from "
        "2025-10-01 to 2026-07-01.",
        frozenset({"forecast_spend"}),
    ),
]
