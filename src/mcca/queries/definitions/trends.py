"""Trend queries: month-over-month change (input to detection + budgeting)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, case, func, select

from mcca.queries.definitions._common import in_range, metric_col
from mcca.queries.registry import QueryDefinition, QueryParam, metric_param, register
from mcca.warehouse.schema import focus_costs

_START = QueryParam("start", required=True)
_END = QueryParam("end", required=True)


def _build_month_over_month(params: dict[str, Any]) -> Select:
    month = func.date_trunc("month", focus_costs.c.charge_period_start)
    monthly = (
        select(month.label("month"), func.sum(metric_col(params)).label("amount"))
        .where(in_range(params))
        .group_by(month)
        .subquery()
    )
    prev = func.lag(monthly.c.amount).over(order_by=monthly.c.month)
    delta = monthly.c.amount - prev
    # Percent change vs the prior month; NULL for the first month and to avoid /0.
    delta_pct = case(
        (prev.is_(None), None),
        (prev == 0, None),
        else_=func.round(delta * 100 / prev, 2),
    )
    return select(
        monthly.c.month,
        monthly.c.amount,
        prev.label("prev_amount"),
        delta.label("delta"),
        delta_pct.label("delta_pct"),
    ).order_by(monthly.c.month)


register(
    QueryDefinition(
        "month_over_month",
        "Monthly spend with absolute and percent change vs the prior month.",
        (_START, _END, metric_param()),
        _build_month_over_month,
    )
)
