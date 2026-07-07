"""Pull + flatten Azure Cost Management Query results (read-only).

The Cost Management Query API returns a columnar result: `properties.columns` (names) and
`properties.rows` (arrays). `flatten_query_response` turns that into typed `AzureCostRow`s
(a pure function, unit-testable without Azure), which `normalize.py` maps to FOCUS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from mcca.ingestion.azure.client import cost_management_client

# Tag keys surfaced as columns in the (synthetic) query result, used for attribution.
_TAG_KEYS = ("team", "environment", "owner")


@dataclass(frozen=True)
class AzureCostRow:
    """One flattened Azure Cost Management row."""

    date: date
    service: str
    resource_group: str | None
    charge_type: str
    currency: str
    cost: Decimal  # actual/billed
    amortized_cost: Decimal  # amortized (RIs/SPs spread)
    quantity: Decimal | None
    unit: str | None
    tags: dict[str, str] = field(default_factory=dict)


def _parse_usage_date(value: Any) -> date:
    """Azure UsageDate is an int/str yyyymmdd (e.g. 20260601)."""
    s = str(int(value))
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal("0")


def flatten_query_response(response: dict[str, Any]) -> list[AzureCostRow]:
    """Flatten a Cost Management Query response (columns+rows) into AzureCostRows."""
    props = response.get("properties", response)
    names = [c["name"] for c in props["columns"]]
    idx = {name: i for i, name in enumerate(names)}

    def get(row: list[Any], name: str) -> Any:
        return row[idx[name]] if name in idx else None

    rows: list[AzureCostRow] = []
    for row in props.get("rows", []):
        tags = {k: get(row, k) for k in _TAG_KEYS if get(row, k)}
        cost = _dec(get(row, "Cost"))
        rows.append(
            AzureCostRow(
                date=_parse_usage_date(get(row, "UsageDate")),
                service=get(row, "ServiceName"),
                resource_group=get(row, "ResourceGroupName"),
                charge_type=get(row, "ChargeType") or "Usage",
                currency=get(row, "Currency") or "USD",
                cost=cost,
                amortized_cost=_dec(get(row, "AmortizedCost")) if "AmortizedCost" in idx else cost,
                quantity=_dec(get(row, "Quantity")) if "Quantity" in idx else None,
                unit=get(row, "UnitOfMeasure"),
                tags=tags,
            )
        )
    return rows


def fetch_cost_management(
    start: date, end: date, *, client: Any | None = None
) -> list[AzureCostRow]:
    """Fetch Azure cost rows for [start, end) (end exclusive), following pages."""
    client = client or cost_management_client()
    responses = client.query(start, end)
    pages = responses if isinstance(responses, list) else [responses]
    rows: list[AzureCostRow] = []
    for page in pages:
        rows.extend(flatten_query_response(page))
    return rows
