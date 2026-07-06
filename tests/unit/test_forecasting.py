"""Forecasting produces horizon points with sensible, widening uncertainty bounds."""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from mcca.forecasting.model import forecast_series
from mcca.forecasting.service import forecast_daily_spend


def _series(days: int, base: float = 100.0, slope: float = 1.0, weekly: float = 0.0) -> list:
    start = date(2026, 1, 1)
    out = []
    for i in range(days):
        season = weekly * math.sin(2 * math.pi * (i % 7) / 7)
        out.append((start + timedelta(days=i), base + slope * i + season))
    return out


def test_empty_history_raises() -> None:
    with pytest.raises(ValueError, match="empty history"):
        forecast_series([], horizon=7)


def test_bad_horizon_raises() -> None:
    with pytest.raises(ValueError, match="horizon"):
        forecast_series(_series(10), horizon=0)


def test_short_history_uses_linear_fallback_with_widening_band() -> None:
    # Weekly wiggle -> nonzero residuals -> a real (widening) uncertainty band.
    fc = forecast_series(_series(10, weekly=8.0), horizon=5, interval=0.8)
    assert fc.model.startswith("linear-trend")
    assert len(fc.points) == 5
    first_width = fc.points[0].upper - fc.points[0].lower
    last_width = fc.points[-1].upper - fc.points[-1].lower
    assert last_width > first_width  # uncertainty grows with the horizon
    for p in fc.points:
        assert p.lower <= p.yhat <= p.upper


def test_long_history_uses_sarimax() -> None:
    fc = forecast_series(_series(60, weekly=8.0), horizon=14, interval=0.8, metric="billed_cost")
    assert fc.model.startswith("SARIMAX")
    assert fc.horizon == 14
    assert len(fc.points) == 14
    assert fc.history_points == 60
    assert fc.metric == "billed_cost"
    for p in fc.points:
        assert p.lower <= p.yhat <= p.upper
        assert p.yhat >= Decimal("0")


class _FakeRepo:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def execute(self, statement: Any) -> list[dict[str, Any]]:
        return self.rows

    def create_schema(self) -> None: ...
    def insert_records(self, records: Any) -> int: ...
    def fetch_all(self) -> list[dict[str, Any]]: ...


def test_forecast_daily_spend_reads_history_via_query() -> None:
    rows = [
        {"day": date(2026, 1, 1) + timedelta(days=i), "amount": Decimal(str(200 + i))}
        for i in range(30)
    ]
    fc = forecast_daily_spend(_FakeRepo(rows), date(2026, 1, 1), date(2026, 1, 31), horizon=10)
    assert len(fc.points) == 10
    assert fc.history_points == 30
