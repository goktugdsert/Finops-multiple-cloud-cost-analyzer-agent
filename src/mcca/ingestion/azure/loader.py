"""Orchestrate Azure ingestion: fetch -> normalize -> load. Read-only."""

from __future__ import annotations

from datetime import date

from mcca.config import Settings, get_settings
from mcca.ingestion.azure.cost_management import fetch_cost_management
from mcca.ingestion.azure.normalize import normalize_records
from mcca.warehouse.repository import WarehouseRepository


def ingest_cost_management(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> int:
    """Fetch [start, end) from Azure Cost Management, normalize to FOCUS, and load."""
    settings = settings or get_settings()
    billing_account_id = settings.azure_billing_account_id or "unknown"
    rows = fetch_cost_management(start, end, client=client)
    records = normalize_records(rows, billing_account_id=billing_account_id)
    # Upsert (not append) so re-ingesting a period reconciles instead of double-counting.
    return repo.upsert_records(records)
