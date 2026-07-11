"""The ingestion orchestration (fetch -> normalize -> load) wires together correctly.

Uses a fake Cost Explorer client (returns the captured fixture, exercises pagination via
NextPageToken) and an in-memory fake repository, so no AWS and no database are needed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from mcca.config import Settings
from mcca.ingestion.aws.loader import ingest_cost_and_usage
from mcca.warehouse.models import FocusRecord
from mcca.warehouse.repository import WarehouseRepository

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_cost_explorer.json"


class FakeCostExplorerClient:
    """Minimal stand-in for the boto3 `ce` client returning two pages once."""

    def __init__(self, page: dict[str, Any]) -> None:
        page_1 = {**page, "NextPageToken": "page-2"}
        page_2 = {**page, "NextPageToken": None}
        self._pages = [page_1, page_2]
        self.calls = 0

    def get_cost_and_usage(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        token = kwargs.get("NextPageToken")
        return self._pages[1] if token == "page-2" else self._pages[0]


class FakeRepository(WarehouseRepository):
    def __init__(self) -> None:
        self.records: list[FocusRecord] = []

    def create_schema(self) -> None:  # pragma: no cover - not used here
        pass

    def insert_records(self, records: Sequence[FocusRecord]) -> int:
        self.records.extend(records)
        return len(records)

    def upsert_records(self, records: Sequence[FocusRecord]) -> int:
        self.records.extend(records)
        return len(records)

    def fetch_all(self) -> list[dict[str, Any]]:  # pragma: no cover - not used here
        return [r.model_dump() for r in self.records]

    def execute(self, statement: Any) -> list[dict[str, Any]]:  # pragma: no cover - not used
        raise NotImplementedError


def test_ingest_paginates_normalizes_and_loads() -> None:
    page = json.loads(FIXTURE.read_text())
    client = FakeCostExplorerClient(page)
    repo = FakeRepository()
    settings = Settings(_env_file=None, aws_billing_account_id="123456789012")

    written = ingest_cost_and_usage(
        repo,
        date(2026, 6, 1),
        date(2026, 6, 2),
        settings=settings,
        client=client,
    )

    # Two pages each with 4 groups -> 8 rows written; account id stamped from settings.
    assert client.calls == 2
    assert written == 8
    assert len(repo.records) == 8
    assert all(r.billing_account_id == "123456789012" for r in repo.records)
    assert all(r.provider_name == "AWS" for r in repo.records)
