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
    EvalCase(
        "detect_anomalies",
        "Were there any cost spikes or steady wasteful spend between 2026-01-01 and 2026-07-01?",
        frozenset({"detect_anomalies"}),
    ),
    EvalCase(
        "spend_vs_budget",
        "Are we on track against our budget for June 2026?",
        frozenset({"spend_vs_budget"}),
    ),
    EvalCase(
        "spend_by_team",
        "How is spend attributed across teams from 2026-01-01 to 2026-04-01?",
        frozenset({"spend_by_team"}),
    ),
    EvalCase(
        "explain_change",
        "Why did our spend change from 2026-05-01 to 2026-06-01 compared with the month before?",
        frozenset({"explain_change"}),
    ),
    EvalCase(
        "route_findings",
        "What cost findings should we act on between 2026-01-01 and 2026-07-01, and who owns them?",
        frozenset({"route_findings"}),
    ),
    # --- v2 capabilities -----------------------------------------------------
    EvalCase(
        "allocate_shared_spend",
        "What is each team's fully-loaded cost including shared/unattributed spend "
        "from 2026-01-01 to 2026-04-01?",
        frozenset({"allocate_shared_spend"}),
    ),
    EvalCase(
        "check_policies",
        "Are we breaching any cost governance policies between 2026-01-01 and 2026-07-01?",
        frozenset({"check_policies"}),
    ),
    EvalCase(
        "review_recommendations",
        "Which cost recommendations are still pending versus approved "
        "between 2026-01-01 and 2026-07-01?",
        frozenset({"review_recommendations"}),
    ),
    EvalCase(
        "search_knowledge",
        "Explain the difference between blended and unblended cost.",
        frozenset({"search_knowledge"}),
    ),
]
