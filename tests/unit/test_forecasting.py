"""Forecasting produces horizon points with sensible, widening uncertainty bounds."""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from mcca.forecasting.model import (
    Forecast,
    ForecastPoint,
    forecast_series,
    summarize_forecast,
)
from mcca.forecasting.service import forecast_daily_spend


def _pt(d: date, yhat: float) -> ForecastPoint:
    return ForecastPoint(
        date=d, yhat=Decimal(str(yhat)), lower=Decimal("0"), upper=Decimal(str(yhat * 2))
    )


def _forecast(points: list, *, model: str = "SARIMAX(1,1,1)(1,1,1,7)", interval: float = 0.8):
    return Forecast(
        model=model,
        metric="billed_cost",
        interval=interval,
        horizon=len(points),
        history_start=None,
        history_end=None,
        history_points=100,
        points=points,
    )


# 2026-01-05 is a Monday, so days 0-4 are Mon-Fri and days 5-6 are Sat-Sun.
_WEEK = [date(2026, 1, 5) + timedelta(days=i) for i in range(7)]


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


def test_summary_reads_weekday_high_direction_from_values() -> None:
    # Weekdays high, weekend low — the real pattern the 9B model once inverted.
    points = [_pt(d, 1000 if d.weekday() < 5 else 800) for d in _WEEK]
    n = summarize_forecast(_forecast(points))
    assert n.weekday_mean == Decimal("1000.00")
    assert n.weekend_mean == Decimal("800.00")
    assert n.higher == "weekdays"  # direction handed to the model as fact, not inference


def test_summary_reads_weekend_high_direction() -> None:
    points = [_pt(d, 500 if d.weekday() < 5 else 900) for d in _WEEK]
    assert summarize_forecast(_forecast(points)).higher == "weekends"


def test_summary_interval_pct_is_explicit() -> None:
    points = [_pt(d, 100) for d in _WEEK]
    assert summarize_forecast(_forecast(points, interval=0.8)).interval_pct == 80
    assert summarize_forecast(_forecast(points, interval=0.9)).interval_pct == 90


def test_sarimax_seasonality_note_forbids_holiday_stories() -> None:
    n = summarize_forecast(_forecast([_pt(d, 100) for d in _WEEK]))
    assert "weekly" in n.seasonality
    assert "holiday" in n.seasonality.lower()  # explicitly warns against holiday narration


def test_linear_model_declares_no_seasonality() -> None:
    points = [_pt(d, 100) for d in _WEEK]
    n = summarize_forecast(_forecast(points, model="linear-trend+residual-band"))
    assert "linear trend only" in n.seasonality
    assert "holiday" in n.seasonality.lower()


def test_forecast_daily_spend_reads_history_via_query() -> None:
    rows = [
        {"day": date(2026, 1, 1) + timedelta(days=i), "amount": Decimal(str(200 + i))}
        for i in range(30)
    ]
    fc = forecast_daily_spend(_FakeRepo(rows), date(2026, 1, 1), date(2026, 1, 31), horizon=10)
    assert len(fc.points) == 10
    assert fc.history_points == 30
