"""Shared pytest fixtures.

Unit tests need no database. The integration test uses a live Postgres (docker compose
up -d) selected via MCCA_DATABASE_URL; it is skipped automatically if unreachable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from mcca.config import Settings
from mcca.warehouse.models import FocusRecord


@pytest.fixture
def settings() -> Settings:
    """Fresh Settings (does not read a developer's real .env)."""
    return Settings(_env_file=None)


@pytest.fixture
def sample_record() -> FocusRecord:
    """A minimal valid FOCUS record with NO tags — attribution should fall back."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    return FocusRecord(
        billed_cost=Decimal("12.34"),
        effective_cost=Decimal("10.00"),
        billing_currency="USD",
        billing_account_id="123456789012",
        billing_period_start=now,
        billing_period_end=datetime(2026, 7, 1, tzinfo=UTC),
        charge_period_start=now,
        charge_period_end=datetime(2026, 6, 2, tzinfo=UTC),
        charge_category="Usage",
        provider_name="AWS",
        service_name="Amazon EC2",
        source_system="test",
    )
