"""Pull + flatten GCP BigQuery billing-export rows (read-only).

The billing export is a table of nested rows (service, sku, project, labels[], credits[],
cost, cost_type, usage). `flatten_billing_rows` turns those into typed `GcpCostRow`s (a
pure function, unit-testable without GCP), which `normalize.py` maps to FOCUS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from mcca.ingestion.gcp.client import bigquery_client

# GCP label keys surfaced for attribution.
_LABEL_KEYS = ("team", "environment", "owner")


@dataclass(frozen=True)
class GcpCostRow:
    """One flattened GCP billing-export row."""

    date: date
    service: str
    sku: str | None
    project_id: str | None
    project_name: str | None
    cost: Decimal  # gross, before credits
    credits_total: Decimal  # sum of credit amounts (usually negative)
    currency: str
    cost_type: str  # regular | tax | adjustment | rounding_error
    quantity: Decimal | None
    unit: str | None
    region: str | None
    tags: dict[str, str] = field(default_factory=dict)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal("0")


def _parse_day(value: Any) -> date:
    """usage_start_time is an ISO timestamp (e.g. 2026-06-01T00:00:00Z)."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _labels_to_tags(labels: list[dict[str, str]] | None) -> dict[str, str]:
    if not labels:
        return {}
    by_key = {label["key"]: label["value"] for label in labels if label.get("value")}
    return {k: by_key[k] for k in _LABEL_KEYS if k in by_key}


def flatten_billing_rows(rows: list[dict[str, Any]]) -> list[GcpCostRow]:
    """Flatten BigQuery billing-export rows into GcpCostRows."""
    flattened: list[GcpCostRow] = []
    for row in rows:
        service = (row.get("service") or {}).get("description")
        sku = (row.get("sku") or {}).get("description")
        project = row.get("project") or {}
        usage = row.get("usage") or {}
        location = row.get("location") or {}
        credits_total = sum((_dec(c.get("amount")) for c in row.get("credits") or []), Decimal("0"))
        flattened.append(
            GcpCostRow(
                date=_parse_day(row.get("usage_start_time")),
                service=service,
                sku=sku,
                project_id=project.get("id"),
                project_name=project.get("name"),
                cost=_dec(row.get("cost")),
                credits_total=credits_total,
                currency=row.get("currency") or "USD",
                cost_type=row.get("cost_type") or "regular",
                quantity=_dec(usage.get("amount")) if usage.get("amount") is not None else None,
                unit=usage.get("unit"),
                region=location.get("region"),
                tags=_labels_to_tags(row.get("labels")),
            )
        )
    return flattened


def fetch_billing_export(start: date, end: date, *, client: Any | None = None) -> list[GcpCostRow]:
    """Fetch GCP billing rows for [start, end) (end exclusive)."""
    client = client or bigquery_client()
    return flatten_billing_rows(client.query(start, end))
