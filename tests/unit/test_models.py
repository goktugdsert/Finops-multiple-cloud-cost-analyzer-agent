"""FocusRecord validates and applies the 'unattributed' fallback when tags are absent."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from mcca.warehouse.models import FocusRecord
from mcca.warehouse.schema import UNATTRIBUTED


def test_attribution_defaults_to_unattributed(sample_record: FocusRecord) -> None:
    assert sample_record.x_team == UNATTRIBUTED
    assert sample_record.x_service == UNATTRIBUTED
    assert sample_record.x_environment == UNATTRIBUTED
    assert sample_record.x_owner == UNATTRIBUTED


def test_costs_are_decimal(sample_record: FocusRecord) -> None:
    assert isinstance(sample_record.billed_cost, Decimal)
    assert isinstance(sample_record.effective_cost, Decimal)


def test_explicit_attribution_is_kept(sample_record: FocusRecord) -> None:
    record = sample_record.model_copy(update={"x_team": "platform", "x_environment": "prod"})
    assert record.x_team == "platform"
    assert record.x_environment == "prod"
    # Unset ones still fall back honestly.
    assert record.x_owner == UNATTRIBUTED


def test_is_estimated_defaults_false(sample_record: FocusRecord) -> None:
    assert sample_record.is_estimated is False


def test_natural_key_ignores_amount_changes(sample_record: FocusRecord) -> None:
    """An estimate and its later final share a key: only the amounts/flag differ."""
    estimate = sample_record.model_copy(
        update={"billed_cost": Decimal("100"), "is_estimated": True}
    )
    final = sample_record.model_copy(update={"billed_cost": Decimal("150"), "is_estimated": False})
    # Same billing line -> same key, so the final reconciles over (not adds to) the estimate.
    assert estimate.natural_key() == final.natural_key()


def test_natural_key_distinguishes_identity_fields(sample_record: FocusRecord) -> None:
    """Different billing lines get different keys (so they never collide on upsert)."""
    base = sample_record.natural_key()
    assert sample_record.model_copy(update={"service_name": "Amazon S3"}).natural_key() != base
    assert sample_record.model_copy(update={"charge_category": "Tax"}).natural_key() != base
    assert sample_record.model_copy(update={"provider_name": "Azure"}).natural_key() != base
    # A different charge day is a different line.
    later = sample_record.model_copy(
        update={"charge_period_start": datetime(2026, 6, 2, tzinfo=UTC)}
    )
    assert later.natural_key() != base
