"""FocusRecord validates and applies the 'unattributed' fallback when tags are absent."""

from __future__ import annotations

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
