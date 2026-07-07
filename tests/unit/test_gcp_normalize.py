"""GCP billing-export -> FOCUS normalization is correct (credits netted, labels mapped)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from mcca.ingestion.gcp.billing_export import flatten_billing_rows
from mcca.ingestion.gcp.normalize import normalize_records, normalize_row
from mcca.warehouse.schema import UNATTRIBUTED

ROWS = [
    {
        "service": {"description": "Compute Engine"},
        "sku": {"description": "N1 core"},
        "usage_start_time": "2026-06-01T00:00:00Z",
        "project": {"id": "platform-prod", "name": "Platform Production"},
        "labels": [
            {"key": "team", "value": "platform"},
            {"key": "environment", "value": "prod"},
            {"key": "owner", "value": "alice"},
        ],
        "cost": 100.0,
        "currency": "USD",
        "cost_type": "regular",
        "usage": {"amount": 2105.26, "unit": "hour"},
        "credits": [{"name": "Committed use discount", "amount": -30.0}],
        "location": {"region": "us-central1"},
    },
    {
        "service": {"description": "Tax"},
        "sku": {"description": "Sales tax"},
        "usage_start_time": "2026-06-01T00:00:00Z",
        "project": {"id": "billing", "name": "Billing"},
        "labels": [],
        "cost": 3.5,
        "currency": "USD",
        "cost_type": "tax",
        "usage": {},
        "credits": [],
        "location": {"region": "us-central1"},
    },
]


@pytest.fixture
def rows():
    return flatten_billing_rows(ROWS)


def test_flatten_reads_nested_fields(rows) -> None:
    gce = rows[0]
    assert gce.service == "Compute Engine"
    assert gce.cost == Decimal("100.0")
    assert gce.credits_total == Decimal("-30.0")
    assert gce.tags == {"team": "platform", "environment": "prod", "owner": "alice"}


def test_normalize_nets_credits(rows) -> None:
    gce = normalize_row(rows[0], billing_account_id="ba-1")
    assert gce.provider_name == "GCP"
    assert gce.billed_cost == Decimal("70.0")  # 100 + (-30)
    assert gce.effective_cost == Decimal("70.0")
    assert gce.list_cost == Decimal("100.0")  # gross before credits
    assert gce.sub_account_id == "platform-prod"
    assert gce.charge_period_start == datetime(2026, 6, 1, tzinfo=UTC)
    assert gce.x_team == "platform"
    assert gce.x_owner == "alice"


def test_tax_row_and_untagged(rows) -> None:
    tax = normalize_records(rows)[1]
    assert tax.charge_category == "Tax"
    assert tax.x_team == UNATTRIBUTED
    assert tax.tags is None
