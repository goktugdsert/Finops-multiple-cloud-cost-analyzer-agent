"""Read/write access to the budgets table (small, config-like data)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, insert, select, update

from mcca.warehouse.schema import budgets

if TYPE_CHECKING:
    from mcca.warehouse.repository import WarehouseRepository


def get_budget(
    repo: WarehouseRepository, scope_type: str = "total", scope_value: str = "all"
) -> dict[str, Any] | None:
    """Return the budget row for a scope, or None if none is set."""
    rows = repo.execute(
        select(budgets).where(
            and_(budgets.c.scope_type == scope_type, budgets.c.scope_value == scope_value)
        )
    )
    return rows[0] if rows else None


def upsert_budget(
    repo: WarehouseRepository,
    monthly_amount: Decimal,
    *,
    scope_type: str = "total",
    scope_value: str = "all",
    currency: str = "USD",
) -> None:
    """Insert or update the monthly budget for a scope."""
    existing = get_budget(repo, scope_type, scope_value)
    if existing is None:
        repo.execute(
            insert(budgets).values(
                scope_type=scope_type,
                scope_value=scope_value,
                monthly_amount=monthly_amount,
                currency=currency,
            )
        )
    else:
        repo.execute(
            update(budgets)
            .where(and_(budgets.c.scope_type == scope_type, budgets.c.scope_value == scope_value))
            .values(monthly_amount=monthly_amount, currency=currency)
        )
