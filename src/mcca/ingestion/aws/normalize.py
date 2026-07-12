"""Normalize raw AWS Cost Explorer rows into FOCUS `FocusRecord`s.

This is where cross-cloud correctness is earned. The mapping choices below are v1
defaults and MUST be validated against the AWS Cost Explorer console before the numbers
are trusted (CLAUDE.md, "where quality lives").

Cost-measure mapping (Cost Explorer metric -> FOCUS column):
    billed_cost     <- NetUnblendedCost   (invoiced amount, after credits/refunds)
    effective_cost  <- NetAmortizedCost   (amortized RIs/SPs, after credits/refunds)
    list_cost       <- ListCost           (on-demand, pre-discount; CUR-grade — see below)
    x_blended_cost  <- BlendedCost         (consolidated average; captured, never billed)
Using the *Net* metrics means credits and refunds are already reflected in the headline
figures; credit/refund line items themselves also appear as their own rows (RECORD_TYPE
Credit/Refund) with negative amounts, which is how Cost Explorer models them. billed_cost is
always UNBLENDED — blended is ingested only into x_blended_cost for comparison.

Commitment discounts: the RECORD_TYPE drives both the charge category and the FOCUS
commitment_discount_* columns (RIFee / SavingsPlanRecurringFee -> Spend; DiscountedUsage /
SavingsPlanCoveredUsage -> Usage). PROVEN-AGAINST-FIXTURE here: the synthetic provider emits
these line items and this mapping is unit-tested. STILL NEEDS REAL DATA: ListCost and true
per-line RI/SP amortization come from the Cost & Usage Report, not the aggregated Cost
Explorer API — the exact figures are confirmable only against a real account's CUR.

Attribution: `attribution_from_tags` maps cost-allocation tags (team/service/environment/
owner) onto the FOCUS x_* columns. Lines without a given tag keep the honest
'unattributed' default — untagged spend is shown, never guessed. (Real per-resource tags
come from the Cost & Usage Report; the synthetic provider emits them directly.)

Numbers here originate from the deterministic Cost Explorer pull, never from an LLM.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from mcca.ingestion.attribution import attribution_from_tags
from mcca.ingestion.aws.cost_explorer import RawCostRow
from mcca.warehouse.models import FocusRecord

# Cost Explorer metrics chosen as the FOCUS headline measures.
BILLED_METRIC = "NetUnblendedCost"
EFFECTIVE_METRIC = "NetAmortizedCost"

# Commitment-discount metadata inferred from the AWS RECORD_TYPE. Populates the FOCUS
# commitment_discount_* columns so RI/SP-covered lines are identifiable. Values: the FOCUS
# CommitmentDiscountType and CommitmentDiscountCategory (Usage = a covered-usage line,
# Spend = a commitment fee/purchase). Everything else leaves the columns NULL (on-demand).
COMMITMENT_BY_RECORD_TYPE: dict[str, tuple[str, str]] = {
    "RIFee": ("Reserved Instance", "Spend"),
    "DiscountedUsage": ("Reserved Instance", "Usage"),
    "SavingsPlanRecurringFee": ("Savings Plan", "Spend"),
    "SavingsPlanUpfrontFee": ("Savings Plan", "Spend"),
    "SavingsPlanCoveredUsage": ("Savings Plan", "Usage"),
    "SavingsPlanNegation": ("Savings Plan", "Usage"),
}


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
    commitment = COMMITMENT_BY_RECORD_TYPE.get(record_type or "")
    commitment_type = commitment[0] if commitment else None
    commitment_category = commitment[1] if commitment else None

    return FocusRecord(
        billed_cost=_amount(row.metrics, BILLED_METRIC),
        effective_cost=_amount(row.metrics, EFFECTIVE_METRIC),
        # ListCost (on-demand, pre-discount) and BlendedCost come from CUR-grade data; when
        # present they let us represent the full list -> billed -> effective discount stack.
        list_cost=_optional_amount(row.metrics, "ListCost"),
        x_blended_cost=_optional_amount(row.metrics, "BlendedCost"),
        billing_currency=_unit(row.metrics, BILLED_METRIC, "USD"),
        billing_account_id=billing_account_id,
        billing_period_start=billing_start,
        billing_period_end=billing_end,
        charge_period_start=charge_start,
        charge_period_end=charge_end,
        charge_category=charge_category,
        charge_description=record_type,
        commitment_discount_type=commitment_type,
        commitment_discount_category=commitment_category,
        commitment_discount_status="Used" if commitment else None,
        provider_name="AWS",
        service_name=row.groups.get("SERVICE"),
        consumed_quantity=_optional_amount(row.metrics, "UsageQuantity"),
        consumed_unit=row.metrics.get("UsageQuantity", {}).get("Unit"),
        is_estimated=row.estimated,  # carried through for estimate->final reconciliation
        tags=row.tags or None,
        source_system="aws.cost_explorer",
        **attribution_from_tags(row.tags),
    )


def normalize_records(
    rows: Iterable[RawCostRow], billing_account_id: str = "unknown"
) -> list[FocusRecord]:
    """Map raw Cost Explorer rows to normalized FOCUS records."""
    return [normalize_row(row, billing_account_id) for row in rows]
