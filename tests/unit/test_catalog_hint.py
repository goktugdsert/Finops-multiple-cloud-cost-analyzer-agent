"""catalog_hint grounds the prompt with exact provider/service names (no DB)."""

from __future__ import annotations

from typing import Any

from mcca.tools.cost_tools import catalog_hint


class CatalogRepo:
    """Fake repo whose execute() returns distinct provider/service rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def execute(self, statement: Any) -> list[dict[str, Any]]:
        return self._rows

    def create_schema(self) -> None: ...
    def insert_records(self, records: Any) -> int: ...
    def fetch_all(self) -> list[dict[str, Any]]: ...


def test_groups_services_by_provider() -> None:
    repo = CatalogRepo(
        [
            {"provider_name": "AWS", "service_name": "Amazon EC2"},
            {"provider_name": "Azure", "service_name": "Virtual Machines"},
            {"provider_name": "GCP", "service_name": "Compute Engine"},
        ]
    )
    hint = catalog_hint(repo)
    assert "AWS: Amazon EC2" in hint
    assert "Azure: Virtual Machines" in hint
    assert "GCP: Compute Engine" in hint
    assert "EXACT" in hint  # instructs the model not to invent names


def test_empty_or_irrelevant_rows_give_no_hint() -> None:
    # Rows without provider/service (e.g. a different query's shape) -> empty hint,
    # never an error (must not break agent construction).
    assert catalog_hint(CatalogRepo([{"billed_cost": 1}])) == ""
    assert catalog_hint(CatalogRepo([])) == ""
