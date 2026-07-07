"""Budget projection math: status classification and variance (pure, no DB)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from mcca.budgets.model import evaluate_budget


def _eval(actual: str, fc_mid: str, budget: str = "9000"):
    return evaluate_budget(
        date(2026, 6, 1),
        "total:all",
        Decimal(budget),
        Decimal(actual),
        Decimal(fc_mid),
        Decimal(fc_mid),  # lo/hi collapsed for these math tests
        Decimal(fc_mid),
    )


def test_over_budget() -> None:
    s = _eval(actual="4000", fc_mid="6000")  # projected 10000 > 9000
    assert s.projected == Decimal("10000")
    assert s.status == "OVER"
    assert s.variance == Decimal("1000")
    assert round(s.variance_pct, 1) == 11.1


def test_at_risk() -> None:
    s = _eval(actual="4000", fc_mid="4400")  # projected 8400 -> 93% of 9000
    assert s.status == "AT_RISK"
    assert s.variance < 0


def test_on_track() -> None:
    s = _eval(actual="3000", fc_mid="3000")  # projected 6000 -> 67%
    assert s.status == "ON_TRACK"


def test_projected_range_carries_bounds() -> None:
    s = evaluate_budget(
        date(2026, 6, 1),
        "total:all",
        Decimal("9000"),
        Decimal("4000"),
        Decimal("5000"),
        Decimal("4500"),
        Decimal("5600"),
    )
    assert s.projected == Decimal("9000")
    assert s.projected_lo == Decimal("8500")
    assert s.projected_hi == Decimal("9600")
