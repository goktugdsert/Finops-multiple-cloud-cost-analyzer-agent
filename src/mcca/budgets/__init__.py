"""Budgets (the 'track vs budget' stage of the loop).

A budget is a user-set monthly target. `spend_vs_budget` combines month-to-date actuals
(from a query) with a forecast for the rest of the month (SARIMAX) to project the
month-end position and flag ON_TRACK / AT_RISK / OVER — the predictive-budgeting pillar.
All figures are deterministic; the LLM never sets or invents a budget number.
"""

from mcca.budgets.model import BudgetStatus, evaluate_budget
from mcca.budgets.service import spend_vs_budget
from mcca.budgets.store import get_budget, upsert_budget

__all__ = [
    "BudgetStatus",
    "evaluate_budget",
    "get_budget",
    "spend_vs_budget",
    "upsert_budget",
]
