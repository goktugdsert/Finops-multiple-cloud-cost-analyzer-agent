"""GCP ingestion orchestration (fetch -> normalize -> load), no GCP and no DB."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from mcca.config import Settings
from mcca.ingestion.gcp.loader import ingest_billing_export
from mcca.ingestion.synthetic.gcp import SyntheticBigQueryClient
from mcca.warehouse.models import FocusRecord
from mcca.warehouse.repository import WarehouseRepository


class FakeRepository(WarehouseRepository):
    def __init__(self) -> None:
        self.records: list[FocusRecord] = []

    def create_schema(self) -> None: ...

    def insert_records(self, records: Sequence[FocusRecord]) -> int:
        self.records.extend(records)
        return len(records)

    def fetch_all(self) -> list[dict[str, Any]]:
        return [r.model_dump() for r in self.records]

    def execute(self, statement: Any) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError


def test_ingest_normalizes_and_loads_gcp() -> None:
    repo = FakeRepository()
    settings = Settings(_env_file=None, gcp_billing_account_id="ba-xyz")
    written = ingest_billing_export(
        repo,
        date(2026, 1, 1),
        date(2026, 1, 8),
        settings=settings,
        client=SyntheticBigQueryClient(),
    )
    assert written == len(repo.records) > 0
    assert all(r.provider_name == "GCP" for r in repo.records)
    assert all(r.billing_account_id == "ba-xyz" for r in repo.records)
