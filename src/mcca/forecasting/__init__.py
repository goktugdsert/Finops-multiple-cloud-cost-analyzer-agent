"""Forecasting (predictive-budgeting pillar).

Historical spend -> forecast at daily granularity, always with an uncertainty interval.
statsmodels SARIMAX (ARIMA family) with a transparent linear-trend fallback. History is
sourced from the fixed query layer, so forecasts are grounded, not fabricated.
"""

from mcca.forecasting.model import Forecast, ForecastPoint, forecast_series
from mcca.forecasting.service import forecast_daily_spend

__all__ = ["Forecast", "ForecastPoint", "forecast_daily_spend", "forecast_series"]
