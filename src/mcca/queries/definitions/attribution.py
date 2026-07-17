"""Attribution queries: spend grouped by the FOCUS x_* attribution dimensions.

Until an allocation policy is defined, most spend groups under 'unattributed' — shown
honestly, per ARCHITECTURE.md.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select

from mcca.queries.definitions._common import in_range, metric_col
from mcca.queries.registry import QueryDefinition, QueryParam, metric_param, register
from mcca.warehouse.schema import focus_costs

_START = QueryParam("start", required=True)
_END = QueryParam("end", required=True)


def _group_by_dimension(column: ColumnElement) -> Callable[[dict[str, Any]], Select]:
    def build(params: dict[str, Any]) -> Select:
        amount = func.sum(metric_col(params)).label("amount")
        return (
            select(column.label(column.name), amount)
            .where(in_range(params))
            .group_by(column)
            .order_by(amount.desc())
        )

    return build


register(
    QueryDefinition(
        "spend_by_team",
        "Spend grouped by attributed team (x_team) over a date range.",
        (_START, _END, metric_param()),
        _group_by_dimension(focus_costs.c.x_team),
    )
)
register(
    QueryDefinition(
        "spend_by_environment",
        "Spend grouped by attributed environment (x_environment) over a date range.",
        (_START, _END, metric_param()),
        _group_by_dimension(focus_costs.c.x_environment),
    )
)
