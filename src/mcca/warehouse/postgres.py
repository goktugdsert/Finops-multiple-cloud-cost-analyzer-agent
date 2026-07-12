"""Postgres implementation of `WarehouseRepository` (v1 default).

The only module that binds the app to Postgres. Uses SQLAlchemy Core against the
`focus_costs` table defined in schema.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, Executable, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.models import FocusRecord
from mcca.warehouse.repository import WarehouseRepository
from mcca.warehouse.schema import focus_costs, metadata

# Columns a restatement is allowed to overwrite on an existing line (its measures and
# estimate flag). The line's identity columns are never updated — they define the key.
_RESTATABLE_COLUMNS = (
    "billed_cost",
    "effective_cost",
    "list_cost",
    "contracted_cost",
    "consumed_quantity",
    "pricing_quantity",
    "is_estimated",
    "x_blended_cost",
    "charge_class",
    "tags",
    "source_system",
)


class PostgresRepository(WarehouseRepository):
    """FOCUS warehouse backed by Postgres via SQLAlchemy Core."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or create_warehouse_engine()

    @property
    def engine(self) -> Engine:
        return self._engine

    def create_schema(self) -> None:
        metadata.create_all(self._engine)

    @staticmethod
    def _row(record: FocusRecord) -> dict[str, Any]:
        """Serialize a record and stamp its natural-identity key for (up)sert."""
        return {**record.model_dump(), "line_key": record.natural_key()}

    def insert_records(self, records: Sequence[FocusRecord]) -> int:
        rows = [self._row(r) for r in records]
        if not rows:
            return 0
        with self._engine.begin() as conn:
            conn.execute(insert(focus_costs), rows)
        return len(rows)

    def upsert_records(self, records: Sequence[FocusRecord]) -> int:
        rows = [self._row(r) for r in records]
        if not rows:
            return 0
        # A single batch may legitimately be re-fetched twice for the same period; collapse
        # duplicate keys within the batch (last wins) so ON CONFLICT never hits the same
        # target row twice in one statement.
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            deduped[row["line_key"]] = row
        batch = list(deduped.values())

        # An ON CONFLICT upsert inlines every row's values into one statement, so a large
        # period would exceed Postgres's 65535 bind-parameter cap. Chunk to stay well under.
        columns = len(batch[0])
        chunk_size = max(1, 60000 // columns)
        with self._engine.begin() as conn:
            for start in range(0, len(batch), chunk_size):
                chunk = batch[start : start + chunk_size]
                stmt = pg_insert(focus_costs).values(chunk)
                set_ = {col: stmt.excluded[col] for col in _RESTATABLE_COLUMNS}
                set_["ingested_at"] = func.now()  # when the line was last restated
                stmt = stmt.on_conflict_do_update(
                    index_elements=[focus_costs.c.line_key], set_=set_
                )
                conn.execute(stmt)
        return len(records)

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
