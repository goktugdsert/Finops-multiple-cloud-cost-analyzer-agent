"""Shared building blocks for query definitions (Core column/filter helpers)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, and_

from mcca.warehouse.schema import focus_costs

_METRIC_COLS = {
    "billed_cost": focus_costs.c.billed_cost,
    "effective_cost": focus_costs.c.effective_cost,
}


def metric_col(params: dict[str, Any]) -> ColumnElement:
    """The cost-measure column selected by the validated `metric` param."""
    return _METRIC_COLS[params["metric"]]


def in_range(params: dict[str, Any]) -> ColumnElement:
    """Filter to charges whose charge_period_start falls in [start, end)."""
    return and_(
        focus_costs.c.charge_period_start >= params["start"],
        focus_costs.c.charge_period_start < params["end"],
    )
