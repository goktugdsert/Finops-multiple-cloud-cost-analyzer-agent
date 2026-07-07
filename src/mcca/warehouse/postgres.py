"""Postgres implementation of `WarehouseRepository` (v1 default).

The only module that binds the app to Postgres. Uses SQLAlchemy Core against the
`focus_costs` table defined in schema.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, Executable, insert, select

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

    def execute(self, statement: Executable) -> list[dict[str, Any]]:
        # begin() commits on success, so this serves both reads (queries) and the
        # occasional write (e.g. upserting a budget). SELECTs return their rows;
        # writes without a RETURNING clause return an empty list.
        with self._engine.begin() as conn:
            result = conn.execute(statement)
            if result.returns_rows:
                return [dict(row) for row in result.mappings()]
            return []
