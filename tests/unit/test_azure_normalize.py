"""Azure Cost Management -> FOCUS normalization is correct and deterministic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from mcca.ingestion.azure.cost_management import flatten_query_response
from mcca.ingestion.azure.normalize import normalize_records, normalize_row
from mcca.warehouse.schema import UNATTRIBUTED

RESPONSE = {
    "properties": {
        "columns": [
            {"name": "Cost", "type": "Number"},
            {"name": "AmortizedCost", "type": "Number"},
            {"name": "UsageDate", "type": "Number"},
            {"name": "ServiceName", "type": "String"},
            {"name": "ResourceGroupName", "type": "String"},
            {"name": "ChargeType", "type": "String"},
            {"name": "Currency", "type": "String"},
            {"name": "Quantity", "type": "Number"},
            {"name": "UnitOfMeasure", "type": "String"},
            {"name": "team", "type": "String"},
            {"name": "environment", "type": "String"},
            {"name": "owner", "type": "String"},
        ],
        "rows": [
            [
                96.0,
                67.2,
                20260601,
                "Virtual Machines",
                "platform-rg",
                "Usage",
                "USD",
                1000.0,
                "Hours",
                "platform",
                "prod",
                "alice",
            ],
            [
                10.0,
                10.0,
                20260601,
                "Azure Managed Disks",
                "shared-rg",
                "Usage",
                "USD",
                83.3,
                "GB-Mo",
                "",
                "",
                "",
            ],
        ],
    }
}


@pytest.fixture
def rows():
    return flatten_query_response(RESPONSE)


def test_flatten_reads_columns(rows) -> None:
    assert len(rows) == 2
    vm = rows[0]
    assert vm.service == "Virtual Machines"
    assert vm.charge_type == "Usage"
    assert vm.cost == Decimal("96.0")
    assert vm.amortized_cost == Decimal("67.2")
    assert vm.tags == {"team": "platform", "environment": "prod", "owner": "alice"}
    assert rows[1].tags == {}  # untagged managed disks


def test_normalize_to_focus(rows) -> None:
    vm = normalize_row(rows[0], billing_account_id="sub-123")
    assert vm.provider_name == "Azure"
    assert vm.billed_cost == Decimal("96.0")
    assert vm.effective_cost == Decimal("67.2")
    assert vm.billing_currency == "USD"
    assert vm.billing_account_id == "sub-123"
    assert vm.sub_account_name == "platform-rg"
    assert vm.charge_category == "Usage"
    assert vm.charge_period_start == datetime(2026, 6, 1, tzinfo=UTC)
    # Attribution comes from tags (shared cross-cloud policy).
    assert vm.x_team == "platform"
    assert vm.x_owner == "alice"


def test_untagged_row_is_unattributed(rows) -> None:
    disks = normalize_records(rows)[1]
    assert disks.x_team == UNATTRIBUTED
    assert disks.tags is None
