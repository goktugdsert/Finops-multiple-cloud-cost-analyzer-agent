"""Visibility queries: totals, per-service, per-charge-category, and time series."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select

from mcca.queries.definitions._common import in_range, metric_col
from mcca.queries.registry import QueryDefinition, QueryParam, metric_param, register
from mcca.warehouse.schema import focus_costs

_START = QueryParam("start", required=True)
_END = QueryParam("end", required=True)


def _build_total_spend(params: dict[str, Any]) -> Select:
    return select(
        func.coalesce(func.sum(focus_costs.c.billed_cost), 0).label("billed_cost"),
        func.coalesce(func.sum(focus_costs.c.effective_cost), 0).label("effective_cost"),
    ).where(in_range(params))


def _build_spend_by_service(params: dict[str, Any]) -> Select:
    amount = func.sum(metric_col(params)).label("amount")
    stmt = select(focus_costs.c.service_name.label("service_name"), amount).where(in_range(params))
    if params.get("charge_category"):
        stmt = stmt.where(focus_costs.c.charge_category == params["charge_category"])
    stmt = stmt.group_by(focus_costs.c.service_name).order_by(amount.desc())
    if params.get("limit"):
        stmt = stmt.limit(params["limit"])
    return stmt


def _build_spend_by_provider(params: dict[str, Any]) -> Select:
    amount = func.sum(metric_col(params)).label("amount")
    return (
        select(focus_costs.c.provider_name.label("provider_name"), amount)
        .where(in_range(params))
        .group_by(focus_costs.c.provider_name)
        .order_by(amount.desc())
    )


def _build_spend_by_charge_category(params: dict[str, Any]) -> Select:
    amount = func.sum(metric_col(params)).label("amount")
    return (
        select(focus_costs.c.charge_category.label("charge_category"), amount)
        .where(in_range(params))
        .group_by(focus_costs.c.charge_category)
        .order_by(amount.desc())
    )


def _build_daily_spend(params: dict[str, Any]) -> Select:
    day = func.date(focus_costs.c.charge_period_start).label("day")
    amount = func.sum(metric_col(params)).label("amount")
    stmt = select(day, amount).where(in_range(params))
    if params.get("service"):
        stmt = stmt.where(focus_costs.c.service_name == params["service"])
    return stmt.group_by(day).order_by(day)


def _build_monthly_spend(params: dict[str, Any]) -> Select:
    month = func.date_trunc("month", focus_costs.c.charge_period_start).label("month")
    amount = func.sum(metric_col(params)).label("amount")
    return select(month, amount).where(in_range(params)).group_by(month).order_by(month)


def _build_daily_spend_by_service(params: dict[str, Any]) -> Select:
    day = func.date(focus_costs.c.charge_period_start).label("day")
    amount = func.sum(metric_col(params)).label("amount")
    stmt = select(day, focus_costs.c.service_name.label("service_name"), amount).where(
        in_range(params)
    )
    if params.get("charge_category"):
        stmt = stmt.where(focus_costs.c.charge_category == params["charge_category"])
    return stmt.group_by(day, focus_costs.c.service_name).order_by(day, focus_costs.c.service_name)


register(
    QueryDefinition(
        "total_spend",
        "Total billed and effective spend across ALL services and clouds over a date range "
        "(a grand total — not for a single service).",
        (_START, _END),
        _build_total_spend,
    )
)
register(
    QueryDefinition(
        "spend_by_service",
        "Spend grouped by service over a date range, highest first. Use this for any "
        "question about a specific service or ranking services.",
        (_START, _END, metric_param(), QueryParam("charge_category"), QueryParam("limit")),
        _build_spend_by_service,
    )
)
register(
    QueryDefinition(
        "spend_by_provider",
        "Spend grouped by cloud provider (AWS/Azure/GCP) over a date range.",
        (_START, _END, metric_param()),
        _build_spend_by_provider,
    )
)
register(
    QueryDefinition(
        "spend_by_charge_category",
        "Spend grouped by FOCUS charge category (Usage/Tax/Credit/Purchase/...).",
        (_START, _END, metric_param()),
        _build_spend_by_charge_category,
    )
)
register(
    QueryDefinition(
        "daily_spend",
        "Daily spend time series over a date range (optionally one service).",
        (_START, _END, metric_param(), QueryParam("service")),
        _build_daily_spend,
    )
)
register(
    QueryDefinition(
        "monthly_spend",
        "Total spend per calendar month across ALL services and clouds (a monthly grand "
        "total — not for a single service).",
        (_START, _END, metric_param()),
        _build_monthly_spend,
    )
)
register(
    QueryDefinition(
        "daily_spend_by_service",
        "Daily spend per service (internal; powers anomaly/waste detection).",
        (_START, _END, metric_param(), QueryParam("charge_category")),
        _build_daily_spend_by_service,
        agent_facing=False,
    )
)


def _build_charge_date_bounds(params: dict[str, Any]) -> Select:
    return select(
        func.min(func.date(focus_costs.c.charge_period_start)).label("min_day"),
        func.max(func.date(focus_costs.c.charge_period_start)).label("max_day"),
    )


register(
    QueryDefinition(
        "charge_date_bounds",
        "Earliest and latest charge dates present (internal; used for budget tracking).",
        (),
        _build_charge_date_bounds,
        agent_facing=False,
    )
)


def _build_service_owners(params: dict[str, Any]) -> Select:
    billed = func.sum(metric_col(params)).label("billed")
    stmt = select(
        focus_costs.c.service_name.label("service_name"),
        focus_costs.c.x_team.label("x_team"),
        focus_costs.c.x_owner.label("x_owner"),
        billed,
    ).where(in_range(params))
    if params.get("charge_category"):
        stmt = stmt.where(focus_costs.c.charge_category == params["charge_category"])
    return stmt.group_by(
        focus_costs.c.service_name, focus_costs.c.x_team, focus_costs.c.x_owner
    ).order_by(billed.desc())


register(
    QueryDefinition(
        "service_owners",
        "Team/owner attribution per service (internal; used to route findings).",
        (_START, _END, metric_param(), QueryParam("charge_category")),
        _build_service_owners,
        agent_facing=False,
    )
)


def _build_service_catalog(params: dict[str, Any]) -> Select:
    return (
        select(focus_costs.c.provider_name, focus_costs.c.service_name)
        .distinct()
        .order_by(focus_costs.c.provider_name, focus_costs.c.service_name)
    )


register(
    QueryDefinition(
        "service_catalog",
        "Distinct provider/service names present (internal; grounds the agent's tool use).",
        (),
        _build_service_catalog,
        agent_facing=False,
    )
)
