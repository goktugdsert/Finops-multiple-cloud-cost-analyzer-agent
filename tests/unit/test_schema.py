"""The FOCUS schema carries the attribution dimension with an 'unattributed' default."""

from __future__ import annotations

from mcca.warehouse.schema import UNATTRIBUTED, focus_costs


def test_attribution_columns_exist() -> None:
    cols = set(focus_costs.c.keys())
    assert {"x_team", "x_service", "x_environment", "x_owner"} <= cols


def test_attribution_columns_default_to_unattributed() -> None:
    for name in ("x_team", "x_service", "x_environment", "x_owner"):
        col = focus_costs.c[name]
        assert col.nullable is False, f"{name} must be NOT NULL"
        assert col.server_default is not None, f"{name} must have a server default"
        assert UNATTRIBUTED in str(col.server_default.arg)


def test_core_focus_and_cost_columns_present() -> None:
    cols = set(focus_costs.c.keys())
    # A few load-bearing FOCUS columns for correct v1 reporting.
    assert {"billed_cost", "effective_cost", "billing_currency"} <= cols
    assert {"charge_period_start", "charge_period_end", "provider_name"} <= cols
