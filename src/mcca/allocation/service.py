"""Allocation orchestration: pull grounded team spend, then apply the allocation policy.

Team spend comes from the fixed `spend_by_team` query, so the direct figures and the shared
('unattributed') pool are themselves traceable to a validated query — allocation only
redistributes them deterministically, never invents a number.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from mcca.allocation.policy import AllocationResult, allocate
from mcca.queries.registry import run_query
from mcca.warehouse.schema import UNATTRIBUTED

if TYPE_CHECKING:
    from datetime import date

    from mcca.warehouse.repository import WarehouseRepository


def allocate_team_spend(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    method: str = "proportional",
    metric: str = "billed_cost",
    weights: dict[str, float] | None = None,
    shared_label: str = UNATTRIBUTED,
) -> AllocationResult:
    """Split shared/unattributed spend over [start, end) across the attributed teams.

    `weights` (team -> weight) is required for `method="weighted"` and ignored otherwise.
    """
    rows = run_query(repo, "spend_by_team", {"start": start, "end": end, "metric": metric}).rows
    direct: dict[str, Decimal] = {}
    pool = Decimal("0")
    for row in rows:
        team = row["x_team"]
        amount = Decimal(str(row["amount"]))
        if team == shared_label:
            pool += amount
        else:
            direct[team] = direct.get(team, Decimal("0")) + amount
    decimal_weights = {k: Decimal(str(v)) for k, v in weights.items()} if weights else None
    return allocate(direct, pool, method=method, weights=decimal_weights)
