"""Normalize raw AWS Cost Explorer rows into FOCUS `FocusRecord`s.

This is where cross-cloud correctness is earned. The mapping choices below are v1
defaults and MUST be validated against the AWS Cost Explorer console before the numbers
are trusted (CLAUDE.md, "where quality lives").

Cost-measure mapping (Cost Explorer metric -> FOCUS column):
    billed_cost     <- NetUnblendedCost   (invoiced amount, after credits/refunds)
    effective_cost  <- NetAmortizedCost   (amortized RIs/SPs, after credits/refunds)
    list_cost       <- None               (needs CUR / pricing API; not asserted in v1)
    contracted_cost <- None               (same)
Using the *Net* metrics means credits and refunds are already reflected in the headline
figures; credit/refund line items themselves also appear as their own rows (RECORD_TYPE
Credit/Refund) with negative amounts, which is how Cost Explorer models them.

Attribution (x_team/x_service/x_environment/x_owner) stays 'unattributed' in v1: mapping
cloud tags to owners is a deferred allocation *policy*, and Cost Explorer's two-group-by
limit is already spent on SERVICE + RECORD_TYPE. The columns exist and default honestly.

Numbers here originate from the deterministic Cost Explorer pull, never from an LLM.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from mcca.ingestion.aws.cost_explorer import RawCostRow
from mcca.warehouse.models import FocusRecord

# Cost Explorer metrics chosen as the FOCUS headline measures.
BILLED_METRIC = "NetUnblendedCost"
EFFECTIVE_METRIC = "NetAmortizedCost"

# AWS RECORD_TYPE dimension -> FOCUS ChargeCategory
# (Usage | Purchase | Tax | Credit | Adjustment). Unknown types fall back to "Usage".
RECORD_TYPE_TO_CHARGE_CATEGORY: dict[str, str] = {
    "Usage": "Usage",
    "Tax": "Tax",
    "Credit": "Credit",
    "Refund": "Credit",
    "RIFee": "Purchase",
    "SavingsPlanRecurringFee": "Purchase",
    "SavingsPlanUpfrontFee": "Purchase",
    "SavingsPlanNegation": "Adjustment",
    "SavingsPlanCoveredUsage": "Usage",
    "DiscountedUsage": "Usage",
    "Fee": "Purchase",
    "Enterprise Discount Program Discount": "Adjustment",
    "Solution Provider Program Discount": "Adjustment",
    "BundledDiscount": "Adjustment",
    "Credit / Refund": "Credit",
}


def _amount(metrics: dict[str, dict[str, str]], name: str) -> Decimal:
    """Read a Cost Explorer metric amount as Decimal (missing/empty -> 0)."""
    raw = metrics.get(name, {}).get("Amount")
    return Decimal(raw) if raw not in (None, "") else Decimal("0")


def _optional_amount(metrics: dict[str, dict[str, str]], name: str) -> Decimal | None:
    raw = metrics.get(name, {}).get("Amount")
    return Decimal(raw) if raw not in (None, "") else None


def _unit(metrics: dict[str, dict[str, str]], name: str, default: str) -> str:
    return metrics.get(name, {}).get("Unit") or default


def _parse_day(value: str) -> datetime:
    """Parse a Cost Explorer 'YYYY-MM-DD' date into a UTC datetime at midnight."""
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _billing_period(day: datetime) -> tuple[datetime, datetime]:
    """Return [first-of-month, first-of-next-month) covering the given day."""
    start = day.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def normalize_row(row: RawCostRow, billing_account_id: str = "unknown") -> FocusRecord:
    """Map one RawCostRow to a FOCUS record."""
    charge_start = _parse_day(row.start)
    charge_end = _parse_day(row.end)
    billing_start, billing_end = _billing_period(charge_start)

    record_type = row.groups.get("RECORD_TYPE")
    charge_category = RECORD_TYPE_TO_CHARGE_CATEGORY.get(record_type or "", "Usage")

    return FocusRecord(
        billed_cost=_amount(row.metrics, BILLED_METRIC),
        effective_cost=_amount(row.metrics, EFFECTIVE_METRIC),
        billing_currency=_unit(row.metrics, BILLED_METRIC, "USD"),
        billing_account_id=billing_account_id,
        billing_period_start=billing_start,
        billing_period_end=billing_end,
        charge_period_start=charge_start,
        charge_period_end=charge_end,
        charge_category=charge_category,
        charge_description=record_type,
        provider_name="AWS",
        service_name=row.groups.get("SERVICE"),
        consumed_quantity=_optional_amount(row.metrics, "UsageQuantity"),
        consumed_unit=row.metrics.get("UsageQuantity", {}).get("Unit"),
        source_system="aws.cost_explorer",
    )


def normalize_records(
    rows: Iterable[RawCostRow], billing_account_id: str = "unknown"
) -> list[FocusRecord]:
    """Map raw Cost Explorer rows to normalized FOCUS records."""
    return [normalize_row(row, billing_account_id) for row in rows]
