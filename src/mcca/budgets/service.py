"""Budget orchestration: actuals (query) + forecast (SARIMAX) vs a stored budget."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from mcca.budgets.model import BudgetStatus, evaluate_budget
from mcca.budgets.store import get_budget
from mcca.forecasting.service import forecast_daily_spend
from mcca.queries.registry import run_query

if TYPE_CHECKING:
    from mcca.warehouse.repository import WarehouseRepository


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _add_month(first_of_month: date) -> date:
    if first_of_month.month == 12:
        return first_of_month.replace(year=first_of_month.year + 1, month=1)
    return first_of_month.replace(month=first_of_month.month + 1)


def _minus_months(first_of_month: date, months: int) -> date:
    total = (first_of_month.year * 12 + (first_of_month.month - 1)) - months
    return date(total // 12, total % 12 + 1, 1)


def _sum(values) -> Decimal:
    return sum(values, Decimal("0"))


def spend_vs_budget(
    repo: WarehouseRepository,
    month: date,
    *,
    scope_type: str = "total",
    scope_value: str = "all",
    metric: str = "billed_cost",
    history_months: int = 6,
) -> BudgetStatus | None:
    """Project spend for `month` (actuals + forecast) and compare to the budget.

    Returns None if no budget is set for the scope. Handles past months (all actual),
    the in-progress month (actual + forecast of remaining days), and future months
    (all forecast).
    """
    budget = get_budget(repo, scope_type, scope_value)
    if budget is None:
        return None
    amount = Decimal(str(budget["monthly_amount"]))

    month_start = _first_of_month(month)
    next_month = _add_month(month_start)

    bounds = run_query(repo, "charge_date_bounds", {}).rows[0]
    last_data = bounds["max_day"]
    if last_data is None:
        return None
    last_plus = last_data + timedelta(days=1)  # first day with no actuals yet

    # Actuals for the elapsed part of the month.
    actual = Decimal("0")
    actual_end = min(next_month, last_plus)
    if actual_end > month_start:
        row = run_query(repo, "total_spend", {"start": month_start, "end": actual_end}).rows[0]
        actual = Decimal(str(row["billed_cost"]))

    # Forecast the remaining days of the month (if any lie beyond the data).
    fc_mid = fc_lo = fc_hi = Decimal("0")
    if next_month > last_plus:
        horizon = (next_month - last_plus).days
        hist_start = _minus_months(_first_of_month(last_data), history_months)
        forecast = forecast_daily_spend(repo, hist_start, last_plus, horizon=horizon, metric=metric)
        points = [p for p in forecast.points if month_start <= p.date < next_month]
        fc_mid = _sum(p.yhat for p in points)
        fc_lo = _sum(p.lower for p in points)
        fc_hi = _sum(p.upper for p in points)

    return evaluate_budget(
        month_start, f"{scope_type}:{scope_value}", amount, actual, fc_mid, fc_lo, fc_hi
    )
