"""Pure budget-projection math (no DB, no LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# A month is AT_RISK once its projected spend reaches this fraction of the budget.
AT_RISK_FRACTION = Decimal("0.9")


@dataclass(frozen=True)
class BudgetStatus:
    month: date
    scope: str
    budget_amount: Decimal
    actual: Decimal  # spent so far this month
    forecast_mid: Decimal  # forecast for the rest of the month
    forecast_lo: Decimal
    forecast_hi: Decimal
    projected: Decimal  # actual + forecast_mid
    projected_lo: Decimal
    projected_hi: Decimal
    variance: Decimal  # projected - budget (positive = over)
    variance_pct: float
    status: str  # ON_TRACK | AT_RISK | OVER


def evaluate_budget(
    month: date,
    scope: str,
    budget_amount: Decimal,
    actual: Decimal,
    forecast_mid: Decimal,
    forecast_lo: Decimal,
    forecast_hi: Decimal,
) -> BudgetStatus:
    """Project month-end spend and classify it against the budget."""
    projected = actual + forecast_mid
    variance = projected - budget_amount
    variance_pct = float(variance / budget_amount * 100) if budget_amount else 0.0
    if projected > budget_amount:
        status = "OVER"
    elif projected >= budget_amount * AT_RISK_FRACTION:
        status = "AT_RISK"
    else:
        status = "ON_TRACK"
    return BudgetStatus(
        month=month,
        scope=scope,
        budget_amount=budget_amount,
        actual=actual,
        forecast_mid=forecast_mid,
        forecast_lo=forecast_lo,
        forecast_hi=forecast_hi,
        projected=projected,
        projected_lo=actual + forecast_lo,
        projected_hi=actual + forecast_hi,
        variance=variance,
        variance_pct=variance_pct,
        status=status,
    )
