"""Time-series forecasting of spend, with uncertainty always shown.

Primary model: SARIMAX (ARIMA family, statsmodels) on the daily series with weekly
seasonality, giving native prediction intervals. If there is too little history or the fit
fails, we fall back to a transparent linear-trend model whose interval comes from the
residual spread and widens with the horizon. Either way the output carries lower/upper
bounds — a forecast is never presented as a point certainty.

A forecast is a deterministic calculation over query results, not an LLM guess: the history
comes from the fixed `daily_spend` query and the math is fully reproducible.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd
from scipy.stats import norm
from statsmodels.tsa.statespace.sarimax import SARIMAX


@dataclass(frozen=True)
class ForecastPoint:
    date: date
    yhat: Decimal
    lower: Decimal
    upper: Decimal


@dataclass(frozen=True)
class Forecast:
    model: str
    metric: str
    interval: float  # e.g. 0.8 for an 80% prediction interval
    horizon: int
    history_start: date | None
    history_end: date | None
    history_points: int
    points: list[ForecastPoint]


@dataclass(frozen=True)
class ForecastNarration:
    """Deterministic narration aids so the LLM can't mis-tell a correct forecast.

    Hands the model the weekday-vs-weekend direction as actual numbers (so it can't invert
    it), an explicit interval percentage (so it can't mislabel it), and a plain statement of
    what seasonality the model does — and does NOT — capture (so it can't invent a holiday
    or calendar effect the model never modeled).
    """

    interval_pct: int
    seasonality: str
    weekday_mean: Decimal
    weekend_mean: Decimal
    higher: str  # "weekdays" | "weekends" | "about the same"


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0.00")
    return (sum(values, Decimal("0")) / len(values)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def summarize_forecast(forecast: Forecast) -> ForecastNarration:
    """Summarize a Forecast into narration guards (pure function over the points)."""
    weekday = [p.yhat for p in forecast.points if p.date.weekday() < 5]
    weekend = [p.yhat for p in forecast.points if p.date.weekday() >= 5]
    weekday_mean, weekend_mean = _mean(weekday), _mean(weekend)

    if not weekday or not weekend:
        higher = "weekdays" if weekday else "weekends" if weekend else "about the same"
    elif weekday_mean > weekend_mean:
        higher = "weekdays"
    elif weekend_mean > weekday_mean:
        higher = "weekends"
    else:
        higher = "about the same"

    if "SARIMAX" in forecast.model:
        seasonality = (
            "weekly (7-day) cycle only — the model has NO awareness of holidays or one-off "
            "calendar events; never attribute a value to one"
        )
    else:
        seasonality = (
            "linear trend only — no weekly seasonality and NO holiday/calendar awareness; "
            "never attribute a value to a holiday"
        )

    return ForecastNarration(
        interval_pct=int(round(forecast.interval * 100)),
        seasonality=seasonality,
        weekday_mean=weekday_mean,
        weekend_mean=weekend_mean,
        higher=higher,
    )


_CENTS = Decimal("0.01")


def _money(value: float) -> Decimal:
    # Spend cannot go below zero; clip and round to cents.
    return Decimal(str(max(0.0, float(value)))).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _to_series(history: list[tuple[date, float]]) -> pd.Series:
    dates = [d for d, _ in history]
    values = [float(v) for _, v in history]
    series = pd.Series(values, index=pd.DatetimeIndex(dates)).sort_index()
    # Regular daily frequency; fill any missing days so the model sees a clean series.
    return series.asfreq("D").interpolate()


def _sarimax(series: pd.Series, horizon: int, interval: float, seasonal_period: int):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = SARIMAX(
            series,
            order=(1, 1, 1),
            seasonal_order=(1, 1, 1, seasonal_period),
            enforce_stationarity=False,
            enforce_invertibility=False,
        )
        fitted = model.fit(disp=False)
        forecast = fitted.get_forecast(steps=horizon)
        mean = np.asarray(forecast.predicted_mean, dtype=float)
        conf = np.asarray(forecast.conf_int(alpha=1 - interval), dtype=float)
    lower, upper = conf[:, 0], conf[:, 1]
    name = f"SARIMAX(1,1,1)(1,1,1,{seasonal_period})"
    return mean, lower, upper, name


def _linear_trend(series: pd.Series, horizon: int, interval: float):
    y = series.to_numpy(dtype=float)
    x = np.arange(len(y))
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    sigma = float(resid.std(ddof=1)) if len(y) > 2 else float(np.std(y) or 1.0)
    z = float(norm.ppf(0.5 + interval / 2))
    steps = np.arange(1, horizon + 1)
    mean = slope * (len(y) - 1 + steps) + intercept
    band = z * sigma * np.sqrt(steps)  # widen with the horizon
    return mean, mean - band, mean + band, "linear-trend+residual-band"


def _flat(series: pd.Series, horizon: int, interval: float):
    """Flat forecast for degenerate input (one point or a constant series).

    Repeats the last value with a nominal, widening uncertainty band. This deliberately
    avoids a least-squares/ARIMA fit on too little data — such a fit emits LAPACK 'DLASCLS'
    warnings and can return NaN. Uncertainty is still shown, never presented as certainty.
    """
    last = float(series.to_numpy(dtype=float)[-1])
    z = float(norm.ppf(0.5 + interval / 2))
    band = z * max(abs(last) * 0.1, 1.0) * np.sqrt(np.arange(1, horizon + 1))
    mean = np.full(horizon, last)
    return mean, mean - band, mean + band, "flat (insufficient history)"


def forecast_series(
    history: list[tuple[date, float]],
    *,
    horizon: int,
    interval: float = 0.8,
    metric: str = "billed_cost",
    seasonal_period: int = 7,
) -> Forecast:
    """Forecast `horizon` days ahead from a daily (date, value) history."""
    if not history:
        raise ValueError("Cannot forecast from empty history.")
    if horizon < 1:
        raise ValueError("horizon must be >= 1.")

    series = _to_series(history)
    y = series.to_numpy(dtype=float)

    # Degenerate history (a single point, non-finite values, or a constant series) can't be
    # fit — a least-squares/ARIMA fit here spams LAPACK 'DLASCLS' warnings and may return NaN.
    # Fall back to a flat forecast. Otherwise: SARIMAX with enough points, else linear trend.
    if len(series) < 3 or not np.isfinite(y).all() or float(np.nanstd(y)) == 0.0:
        mean, lower, upper, name = _flat(series, horizon, interval)
    elif len(series) >= 2 * seasonal_period + 2:
        try:
            mean, lower, upper, name = _sarimax(series, horizon, interval, seasonal_period)
        except Exception:  # noqa: BLE001 - any fit failure -> transparent fallback
            mean, lower, upper, name = _linear_trend(series, horizon, interval)
    else:
        mean, lower, upper, name = _linear_trend(series, horizon, interval)

    last = series.index[-1].date()
    points = [
        ForecastPoint(
            date=last + timedelta(days=i + 1),
            yhat=_money(mean[i]),
            lower=_money(lower[i]),
            upper=_money(upper[i]),
        )
        for i in range(horizon)
    ]
    return Forecast(
        model=name,
        metric=metric,
        interval=interval,
        horizon=horizon,
        history_start=series.index[0].date(),
        history_end=last,
        history_points=int(len(series)),
        points=points,
    )
