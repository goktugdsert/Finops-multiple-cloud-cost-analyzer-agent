"""Normalize GCP billing-export rows into FOCUS `FocusRecord`s.

Same target schema. GCP applies discounts (committed-use, sustained-use) as *credits*
inside each row rather than as separate line items, so:
    billed_cost     <- cost + credits   (net of credits — what you're invoiced)
    effective_cost  <- cost + credits   (GCP has no RI-style amortization gap)
Attribution reuses the shared tag policy (GCP labels). Numbers come from the deterministic
billing export, never an LLM.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from mcca.ingestion.attribution import attribution_from_tags
from mcca.ingestion.gcp.billing_export import GcpCostRow
from mcca.warehouse.models import FocusRecord

# GCP cost_type -> FOCUS ChargeCategory.
COST_TYPE_TO_CATEGORY: dict[str, str] = {
    "regular": "Usage",
    "tax": "Tax",
    "adjustment": "Adjustment",
    "rounding_error": "Adjustment",
}


def _billing_period(day: datetime) -> tuple[datetime, datetime]:
    start = day.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def normalize_row(row: GcpCostRow, billing_account_id: str = "unknown") -> FocusRecord:
    """Map one GcpCostRow to a FOCUS record."""
    charge_start = datetime(row.date.year, row.date.month, row.date.day, tzinfo=UTC)
    charge_end = charge_start + timedelta(days=1)
    billing_start, billing_end = _billing_period(charge_start)

    net = row.cost + row.credits_total
    return FocusRecord(
        billed_cost=net,
        effective_cost=net,
        list_cost=row.cost,  # gross list price before credits
        billing_currency=row.currency,
        billing_account_id=billing_account_id,
        sub_account_id=row.project_id,
        sub_account_name=row.project_name,
        billing_period_start=billing_start,
        billing_period_end=billing_end,
        charge_period_start=charge_start,
        charge_period_end=charge_end,
        charge_category=COST_TYPE_TO_CATEGORY.get(row.cost_type, "Usage"),
        charge_description=row.sku,
        provider_name="GCP",
        service_name=row.service,
        region_id=row.region,
        consumed_quantity=row.quantity,
        consumed_unit=row.unit,
        tags=row.tags or None,
        source_system="gcp.billing_export",
        **attribution_from_tags(row.tags),
    )


def normalize_records(
    rows: Iterable[GcpCostRow], billing_account_id: str = "unknown"
) -> list[FocusRecord]:
    """Map raw GCP billing rows to normalized FOCUS records."""
    return [normalize_row(row, billing_account_id) for row in rows]
