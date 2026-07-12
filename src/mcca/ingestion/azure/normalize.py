"""Normalize Azure Cost Management rows into FOCUS `FocusRecord`s.

Same target schema as AWS — that's the whole point of FOCUS. Attribution reuses the shared
tag policy so team/owner mean the same thing cross-cloud. Numbers originate from the
deterministic Azure query, never from an LLM.

Cost-measure mapping:
    billed_cost     <- Cost            (actual)
    effective_cost  <- AmortizedCost   (RIs/reservations spread)
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from mcca.ingestion.attribution import attribution_from_tags
from mcca.ingestion.azure.cost_management import AzureCostRow
from mcca.warehouse.models import FocusRecord

# Azure ChargeType -> FOCUS ChargeCategory.
CHARGE_TYPE_TO_CATEGORY: dict[str, str] = {
    "Usage": "Usage",
    "Purchase": "Purchase",
    "Refund": "Credit",
    "UnusedReservation": "Adjustment",
    "UnusedSavingsPlan": "Adjustment",
    "Reservation": "Purchase",
}

# Azure ChargeType -> FOCUS commitment_discount_type, for reservation/savings-plan charges.
COMMITMENT_BY_CHARGE_TYPE: dict[str, str] = {
    "Reservation": "Reserved Instance",
    "UnusedReservation": "Reserved Instance",
    "UnusedSavingsPlan": "Savings Plan",
}


def _billing_period(day: datetime) -> tuple[datetime, datetime]:
    start = day.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def normalize_row(row: AzureCostRow, billing_account_id: str = "unknown") -> FocusRecord:
    """Map one AzureCostRow to a FOCUS record."""
    charge_start = datetime(row.date.year, row.date.month, row.date.day, tzinfo=UTC)
    charge_end = charge_start + timedelta(days=1)
    billing_start, billing_end = _billing_period(charge_start)

    return FocusRecord(
        billed_cost=row.cost,
        effective_cost=row.amortized_cost,
        billing_currency=row.currency,
        billing_account_id=billing_account_id,
        sub_account_id=row.resource_group,
        sub_account_name=row.resource_group,
        billing_period_start=billing_start,
        billing_period_end=billing_end,
        charge_period_start=charge_start,
        charge_period_end=charge_end,
        charge_category=CHARGE_TYPE_TO_CATEGORY.get(row.charge_type, "Usage"),
        charge_description=row.charge_type,
        commitment_discount_type=COMMITMENT_BY_CHARGE_TYPE.get(row.charge_type),
        commitment_discount_status=("Unused" if row.charge_type == "UnusedReservation" else None),
        provider_name="Azure",
        service_name=row.service,
        consumed_quantity=row.quantity,
        consumed_unit=row.unit,
        tags=row.tags or None,
        source_system="azure.cost_management",
        **attribution_from_tags(row.tags),
    )


def normalize_records(
    rows: Iterable[AzureCostRow], billing_account_id: str = "unknown"
) -> list[FocusRecord]:
    """Map raw Azure cost rows to normalized FOCUS records."""
    return [normalize_row(row, billing_account_id) for row in rows]
