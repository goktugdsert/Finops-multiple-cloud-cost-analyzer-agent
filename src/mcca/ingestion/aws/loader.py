"""Orchestrate AWS ingestion: fetch -> normalize -> load into the warehouse.

Depends only on the `WarehouseRepository` interface, never on Postgres directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from mcca.config import Settings, get_settings
from mcca.ingestion.aws.cost_explorer import fetch_cost_and_usage
from mcca.ingestion.aws.normalize import normalize_records
from mcca.warehouse.models import FocusRecord
from mcca.warehouse.repository import WarehouseRepository


def load_records(repo: WarehouseRepository, records: Sequence[FocusRecord]) -> int:
    """Reconcile normalized records into the warehouse (upsert on natural identity).

    Uses upsert so re-ingesting an overlapping period corrects existing lines and applies
    estimate->final restatements in place, instead of double-counting.
    """
    return repo.upsert_records(records)


def ingest_cost_and_usage(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    settings: Settings | None = None,
    client: object | None = None,
) -> int:
    """Fetch [start, end) from Cost Explorer, normalize to FOCUS, and reconcile. Read-only.

    Returns the number of rows processed. `end` is exclusive, matching Cost Explorer.
    """
    settings = settings or get_settings()
    billing_account_id = settings.aws_billing_account_id or "unknown"
    rows = fetch_cost_and_usage(start, end, client=client)
    records = normalize_records(rows, billing_account_id=billing_account_id)
    return load_records(repo, records)
