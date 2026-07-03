"""Postgres implementation of `WarehouseRepository` (v1 default).

The only module that binds the app to Postgres. Uses SQLAlchemy Core against the
`focus_costs` table defined in schema.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, insert, select

from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.models import FocusRecord
from mcca.warehouse.repository import WarehouseRepository
from mcca.warehouse.schema import focus_costs, metadata


class PostgresRepository(WarehouseRepository):
    """FOCUS warehouse backed by Postgres via SQLAlchemy Core."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or create_warehouse_engine()

    @property
    def engine(self) -> Engine:
        return self._engine

    def create_schema(self) -> None:
        metadata.create_all(self._engine)

    def insert_records(self, records: Sequence[FocusRecord]) -> int:
        rows = [r.model_dump() for r in records]
        if not rows:
            return 0
        with self._engine.begin() as conn:
            conn.execute(insert(focus_costs), rows)
        return len(rows)

    def fetch_all(self) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            result = conn.execute(select(focus_costs))
            return [dict(row) for row in result.mappings()]

    def run_named_query(
        self, name: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        # The fixed query registry lands in build step 3. Until then this raises so no
        # ad-hoc SQL path exists by accident.
        raise NotImplementedError(
            "Named query registry not built yet (build step 3). "
            "Cost figures must come from a registered, validated query."
        )
