"""Azure ingestion orchestration (fetch -> normalize -> load), no Azure and no DB."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from mcca.config import Settings
from mcca.ingestion.azure.loader import ingest_cost_management
from mcca.ingestion.synthetic.azure import SyntheticAzureClient
from mcca.warehouse.models import FocusRecord
from mcca.warehouse.repository import WarehouseRepository


class FakeRepository(WarehouseRepository):
    def __init__(self) -> None:
        self.records: list[FocusRecord] = []

    def create_schema(self) -> None: ...

    def insert_records(self, records: Sequence[FocusRecord]) -> int:
        self.records.extend(records)
        return len(records)

    def upsert_records(self, records: Sequence[FocusRecord]) -> int:
        self.records.extend(records)
        return len(records)

    def fetch_all(self) -> list[dict[str, Any]]:
        return [r.model_dump() for r in self.records]

    def execute(self, statement: Any) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError


def test_ingest_normalizes_and_loads_azure() -> None:
    repo = FakeRepository()
    settings = Settings(_env_file=None, azure_billing_account_id="sub-abc")
    written = ingest_cost_management(
        repo,
        date(2026, 1, 1),
        date(2026, 1, 8),
        settings=settings,
        client=SyntheticAzureClient(),
    )
    assert written == len(repo.records) > 0
    assert all(r.provider_name == "Azure" for r in repo.records)
    assert all(r.billing_account_id == "sub-abc" for r in repo.records)
