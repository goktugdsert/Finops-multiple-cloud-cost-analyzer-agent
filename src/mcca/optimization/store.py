"""Persist human decisions on recommendations (read/write to recommendation_decisions).

Small, config-like data — the same interface pattern as budgets/store.py. This is the ONLY
state the approval workflow writes; it never touches the FOCUS cost data or infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, insert, select, update

from mcca.optimization.model import DECISION_STATUSES, Recommendation
from mcca.warehouse.schema import recommendation_decisions

if TYPE_CHECKING:
    from datetime import date

    from mcca.warehouse.repository import WarehouseRepository


def get_decisions(
    repo: WarehouseRepository, keys: set[str] | None = None
) -> dict[str, dict[str, Any]]:
    """Return persisted decisions keyed by rec_key (optionally filtered to `keys`)."""
    rows = repo.execute(select(recommendation_decisions))
    return {r["rec_key"]: r for r in rows if keys is None or r["rec_key"] in keys}


def record_decision(
    repo: WarehouseRepository,
    rec_key: str,
    status: str,
    *,
    decided_by: str | None = None,
    note: str | None = None,
    snooze_until: date | None = None,
    snapshot: Recommendation | None = None,
) -> None:
    """Upsert a human's decision on a recommendation. Records intent only — no action taken."""
    if status not in DECISION_STATUSES:
        raise ValueError(f"Invalid decision {status!r}; choose from {list(DECISION_STATUSES)}")

    values: dict[str, Any] = {
        "status": status,
        "decided_by": decided_by,
        "note": note,
        "snooze_until": snooze_until,
        "decided_at": func.now(),
    }
    if snapshot is not None:
        values.update(
            source=snapshot.source,
            kind=snapshot.kind,
            severity=snapshot.severity,
            scope=snapshot.scope,
            summary=snapshot.summary,
            action=snapshot.action,
        )

    existing = repo.execute(
        select(recommendation_decisions.c.id).where(recommendation_decisions.c.rec_key == rec_key)
    )
    if existing:
        repo.execute(
            update(recommendation_decisions)
            .where(recommendation_decisions.c.rec_key == rec_key)
            .values(**values)
        )
    else:
        repo.execute(insert(recommendation_decisions).values(rec_key=rec_key, **values))
