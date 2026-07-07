"""Explain a spend change by decomposing it into per-service drivers.

Compares a period to a prior period (by default the equal-length window immediately
before it) and ranks services by how much they moved — the deterministic answer to
"why did spend change?". History comes from the fixed `spend_by_service` query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from mcca.queries.registry import run_query

if TYPE_CHECKING:
    from mcca.warehouse.repository import WarehouseRepository


@dataclass(frozen=True)
class Driver:
    service: str
    current: Decimal
    prior: Decimal
    delta: Decimal  # current - prior (positive = increase)


@dataclass(frozen=True)
class ChangeExplanation:
    current_start: date
    current_end: date
    prior_start: date
    prior_end: date
    metric: str
    current_total: Decimal
    prior_total: Decimal
    total_delta: Decimal
    drivers: list[Driver]


def _by_service(
    repo: WarehouseRepository, start: date, end: date, metric: str
) -> dict[str, Decimal]:
    rows = run_query(
        repo,
        "spend_by_service",
        {"start": start, "end": end, "metric": metric, "charge_category": "Usage"},
    ).rows
    return {r["service_name"]: Decimal(str(r["amount"])) for r in rows}


def explain_change(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    metric: str = "billed_cost",
    top_n: int = 5,
    prior_start: date | None = None,
    prior_end: date | None = None,
) -> ChangeExplanation:
    """Rank per-service drivers of the spend change for [start, end) vs a prior period."""
    if prior_start is None or prior_end is None:
        length = (end - start).days
        prior_end = start
        prior_start = start - timedelta(days=length)

    current = _by_service(repo, start, end, metric)
    prior = _by_service(repo, prior_start, prior_end, metric)

    drivers = [
        Driver(
            service,
            current.get(service, Decimal("0")),
            prior.get(service, Decimal("0")),
            current.get(service, Decimal("0")) - prior.get(service, Decimal("0")),
        )
        for service in set(current) | set(prior)
    ]
    drivers.sort(key=lambda d: abs(d.delta), reverse=True)

    current_total = sum(current.values(), Decimal("0"))
    prior_total = sum(prior.values(), Decimal("0"))
    return ChangeExplanation(
        current_start=start,
        current_end=end,
        prior_start=prior_start,
        prior_end=prior_end,
        metric=metric,
        current_total=current_total,
        prior_total=prior_total,
        total_delta=current_total - prior_total,
        drivers=drivers[:top_n],
    )
