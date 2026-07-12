"""AWS Cost Explorer -> FOCUS normalization is correct and deterministic.

Runs against a captured Cost Explorer response shape (no live AWS). Verifies cost-measure
mapping, charge-category derivation, currency, usage, billing period, and the honest
'unattributed' attribution fallback.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mcca.ingestion.aws.cost_explorer import RawCostRow, flatten_response
from mcca.ingestion.aws.normalize import normalize_records, normalize_row
from mcca.warehouse.schema import UNATTRIBUTED

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_cost_explorer.json"


@pytest.fixture
def rows() -> list[RawCostRow]:
    page = json.loads(FIXTURE.read_text())
    return flatten_response([page])


def test_flatten_labels_group_keys(rows: list[RawCostRow]) -> None:
    assert len(rows) == 4
    ec2 = rows[0]
    assert ec2.groups == {
        "SERVICE": "Amazon Elastic Compute Cloud - Compute",
        "RECORD_TYPE": "Usage",
    }
    assert ec2.start == "2026-06-01"
    assert ec2.end == "2026-06-02"
    assert ec2.estimated is True


def test_cost_measures_use_net_metrics(rows: list[RawCostRow]) -> None:
    ec2 = normalize_row(rows[0], billing_account_id="123456789012")
    # billed <- NetUnblendedCost, effective <- NetAmortizedCost (not the gross values).
    assert ec2.billed_cost == Decimal("100.0000000000")
    assert ec2.effective_cost == Decimal("90.0000000000")
    assert isinstance(ec2.billed_cost, Decimal)
    assert ec2.billing_currency == "USD"
    assert ec2.billing_account_id == "123456789012"


def test_charge_category_mapping(rows: list[RawCostRow]) -> None:
    by_desc = {r.charge_description: r for r in normalize_records(rows)}
    assert by_desc["Usage"].charge_category == "Usage"
    assert by_desc["Credit"].charge_category == "Credit"
    assert by_desc["Tax"].charge_category == "Tax"


def test_credits_are_negative(rows: list[RawCostRow]) -> None:
    credit = next(r for r in normalize_records(rows) if r.charge_description == "Credit")
    assert credit.billed_cost == Decimal("-15.0000000000")


def test_usage_quantity_and_service(rows: list[RawCostRow]) -> None:
    ec2 = normalize_row(rows[0])
    assert ec2.consumed_quantity == Decimal("744.0000000000")
    assert ec2.consumed_unit == "Hrs"
    assert ec2.service_name == "Amazon Elastic Compute Cloud - Compute"
    assert ec2.provider_name == "AWS"
    assert ec2.source_system == "aws.cost_explorer"


def test_billing_period_and_charge_period(rows: list[RawCostRow]) -> None:
    ec2 = normalize_row(rows[0])
    assert ec2.charge_period_start == datetime(2026, 6, 1, tzinfo=UTC)
    assert ec2.charge_period_end == datetime(2026, 6, 2, tzinfo=UTC)
    # Billing period spans the whole month, end-exclusive.
    assert ec2.billing_period_start == datetime(2026, 6, 1, tzinfo=UTC)
    assert ec2.billing_period_end == datetime(2026, 7, 1, tzinfo=UTC)


def test_attribution_defaults_to_unattributed(rows: list[RawCostRow]) -> None:
    for record in normalize_records(rows):
        assert record.x_team == UNATTRIBUTED
        assert record.x_service == UNATTRIBUTED
        assert record.x_environment == UNATTRIBUTED
        assert record.x_owner == UNATTRIBUTED


def test_tags_populate_attribution_columns() -> None:
    row = RawCostRow(
        start="2026-06-01",
        end="2026-06-02",
        groups={"SERVICE": "Amazon EC2", "RECORD_TYPE": "Usage"},
        metrics={
            "NetUnblendedCost": {"Amount": "10.00", "Unit": "USD"},
            "NetAmortizedCost": {"Amount": "8.00", "Unit": "USD"},
        },
        estimated=False,
        tags={"team": "platform", "environment": "prod", "owner": "alice"},
    )
    record = normalize_row(row)
    assert record.x_team == "platform"
    assert record.x_environment == "prod"
    assert record.x_owner == "alice"
    assert record.tags == {"team": "platform", "environment": "prod", "owner": "alice"}


def test_untagged_line_stays_unattributed() -> None:
    row = RawCostRow(
        start="2026-06-01",
        end="2026-06-02",
        groups={"SERVICE": "Tax", "RECORD_TYPE": "Tax"},
        metrics={
            "NetUnblendedCost": {"Amount": "9.99", "Unit": "USD"},
            "NetAmortizedCost": {"Amount": "9.99", "Unit": "USD"},
        },
        estimated=False,
    )
    record = normalize_row(row)
    assert record.x_team == UNATTRIBUTED
    assert record.tags is None


def _row(record_type: str, metrics: dict) -> RawCostRow:
    return RawCostRow(
        start="2026-06-01",
        end="2026-06-02",
        groups={"SERVICE": "Amazon Elastic Compute Cloud - Compute", "RECORD_TYPE": record_type},
        metrics=metrics,
        estimated=False,
    )


def test_savings_plan_covered_usage_normalizes_with_commitment_metadata() -> None:
    # A SavingsPlanCoveredUsage line: billed $0 (covered), list = on-demand, effective = SP.
    row = _row(
        "SavingsPlanCoveredUsage",
        {
            "NetUnblendedCost": {"Amount": "0.00", "Unit": "USD"},
            "NetAmortizedCost": {"Amount": "21.00", "Unit": "USD"},
            "ListCost": {"Amount": "28.80", "Unit": "USD"},
            "BlendedCost": {"Amount": "21.00", "Unit": "USD"},
        },
    )
    rec = normalize_row(row)
    assert rec.charge_category == "Usage"  # covered usage is still Usage
    assert rec.billed_cost == Decimal("0.00")
    assert rec.list_cost == Decimal("28.80")  # on-demand price it displaced
    assert rec.list_cost > rec.billed_cost  # the SP discount is now representable
    assert rec.commitment_discount_type == "Savings Plan"
    assert rec.commitment_discount_category == "Usage"
    assert rec.commitment_discount_status == "Used"


def test_savings_plan_recurring_fee_is_a_purchase() -> None:
    row = _row(
        "SavingsPlanRecurringFee",
        {
            "NetUnblendedCost": {"Amount": "21.00", "Unit": "USD"},
            "NetAmortizedCost": {"Amount": "0.00", "Unit": "USD"},
        },
    )
    rec = normalize_row(row)
    assert rec.charge_category == "Purchase"
    assert rec.commitment_discount_type == "Savings Plan"
    assert rec.commitment_discount_category == "Spend"


def test_contracted_cost_is_ingested_between_list_and_billed() -> None:
    row = _row(
        "Usage",
        {
            "NetUnblendedCost": {"Amount": "90.00", "Unit": "USD"},
            "NetAmortizedCost": {"Amount": "90.00", "Unit": "USD"},
            "ListCost": {"Amount": "100.00", "Unit": "USD"},
            "ContractedCost": {"Amount": "90.00", "Unit": "USD"},
        },
    )
    rec = normalize_row(row)
    assert rec.list_cost == Decimal("100.00")
    assert rec.contracted_cost == Decimal("90.00")
    # The FOCUS discount stack holds: list >= contracted >= billed.
    assert rec.list_cost >= rec.contracted_cost >= rec.billed_cost


def test_blended_cost_is_captured_but_never_billed() -> None:
    # RI-covered usage: blended (consolidated avg) differs from the unblended billed amount.
    row = _row(
        "Usage",
        {
            "NetUnblendedCost": {"Amount": "100.00", "Unit": "USD"},
            "NetAmortizedCost": {"Amount": "72.00", "Unit": "USD"},
            "BlendedCost": {"Amount": "72.00", "Unit": "USD"},
        },
    )
    rec = normalize_row(row)
    assert rec.billed_cost == Decimal("100.00")  # billed is ALWAYS unblended
    assert rec.x_blended_cost == Decimal("72.00")  # blended captured separately
    assert rec.x_blended_cost != rec.billed_cost


def test_on_demand_line_has_no_commitment_metadata() -> None:
    row = _row(
        "Usage",
        {
            "NetUnblendedCost": {"Amount": "10.00", "Unit": "USD"},
            "NetAmortizedCost": {"Amount": "10.00", "Unit": "USD"},
        },
    )
    rec = normalize_row(row)
    assert rec.commitment_discount_type is None
    assert rec.commitment_discount_status is None


def test_billing_period_rolls_over_december() -> None:
    row = RawCostRow(
        start="2026-12-15",
        end="2026-12-16",
        groups={"SERVICE": "Amazon EC2", "RECORD_TYPE": "Usage"},
        metrics={
            "NetUnblendedCost": {"Amount": "1.00", "Unit": "USD"},
            "NetAmortizedCost": {"Amount": "1.00", "Unit": "USD"},
        },
        estimated=False,
    )
    record = normalize_row(row)
    assert record.billing_period_start == datetime(2026, 12, 1, tzinfo=UTC)
    assert record.billing_period_end == datetime(2027, 1, 1, tzinfo=UTC)
