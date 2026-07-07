"""Orchestrate GCP ingestion: fetch -> normalize -> load. Read-only."""

from __future__ import annotations

from datetime import date

from mcca.config import Settings, get_settings
from mcca.ingestion.gcp.billing_export import fetch_billing_export
from mcca.ingestion.gcp.normalize import normalize_records
from mcca.warehouse.repository import WarehouseRepository


def ingest_billing_export(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> int:
    """Fetch [start, end) from the GCP billing export, normalize to FOCUS, and load."""
    settings = settings or get_settings()
    billing_account_id = settings.gcp_billing_account_id or "unknown"
    rows = fetch_billing_export(start, end, client=client)
    records = normalize_records(rows, billing_account_id=billing_account_id)
    return repo.insert_records(records)
