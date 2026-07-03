"""The warehouse seam: an abstract repository the rest of the app depends on.

Query tools and ingestion talk to a `WarehouseRepository`, never to Postgres directly.
Swapping to BigQuery/Snowflake later means adding a new implementation of this
interface — no changes to `queries/`, `tools/`, or `agent/`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from mcca.warehouse.models import FocusRecord


class WarehouseRepository(ABC):
    """Abstract data-access interface over the FOCUS warehouse."""

    @abstractmethod
    def create_schema(self) -> None:
        """Create the FOCUS schema if it does not already exist."""

    @abstractmethod
    def insert_records(self, records: Sequence[FocusRecord]) -> int:
        """Persist normalized FOCUS records. Returns the number of rows written."""

    @abstractmethod
    def fetch_all(self) -> list[dict[str, Any]]:
        """Return all rows as dicts. Utility for tests/inspection — not a query tool.

        Deterministic reporting goes through the fixed query layer, not this method.
        """

    @abstractmethod
    def run_named_query(
        self, name: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a pre-registered, validated query by name and return rows.

        This is the ONLY sanctioned path for producing cost figures. `name` must refer
        to a query in the fixed registry; arbitrary/LLM-authored SQL is not accepted.
        """
