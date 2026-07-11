"""The warehouse seam: an abstract repository the rest of the app depends on.

Query tools and ingestion talk to a `WarehouseRepository`, never to Postgres directly.
Swapping to BigQuery/Snowflake later means adding a new implementation of this
interface — no changes to `queries/`, `tools/`, or `agent/`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from mcca.warehouse.models import FocusRecord

if TYPE_CHECKING:
    from sqlalchemy import Executable


class WarehouseRepository(ABC):
    """Abstract data-access interface over the FOCUS warehouse."""

    @abstractmethod
    def create_schema(self) -> None:
        """Create the FOCUS schema if it does not already exist."""

    @abstractmethod
    def insert_records(self, records: Sequence[FocusRecord]) -> int:
        """Persist normalized FOCUS records (plain append). Returns rows written.

        Used for one-shot loads into a fresh warehouse. Repeated ingestion of overlapping
        periods should go through `upsert_records` to avoid double-counting.
        """

    @abstractmethod
    def upsert_records(self, records: Sequence[FocusRecord]) -> int:
        """Reconcile normalized FOCUS records against existing rows by natural identity.

        Rows are keyed on `FocusRecord.natural_key()` (the line's billing identity, not its
        amounts). A record whose key already exists overwrites that row's cost measures,
        quantities and estimate flag — so re-ingesting a period corrects in place and an
        estimate is replaced by its final restatement, rather than duplicating. Returns the
        number of records processed.
        """

    @abstractmethod
    def fetch_all(self) -> list[dict[str, Any]]:
        """Return all rows as dicts. Utility for tests/inspection — not a query tool.

        Deterministic reporting goes through the fixed query layer, not this method.
        """

    @abstractmethod
    def execute(self, statement: Executable) -> list[dict[str, Any]]:
        """Execute a prepared SQLAlchemy Core statement and return mapped rows.

        The query LAYER (mcca.queries) decides which statements exist — a fixed,
        validated set built from the schema, never arbitrary/LLM-authored SQL. The
        repository just runs what it is handed. There is no string-SQL entry point, so
        the agent cannot produce a figure outside the registered query set.
        """
