"""Forecast orchestration: pull grounded history from the query layer, then model it.

History is read through the fixed `daily_spend` query — so the numbers the forecast is
built on are themselves traceable to a validated query, not fabricated.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from mcca.forecasting.model import Forecast, forecast_series
from mcca.queries.registry import run_query

if TYPE_CHECKING:
    from mcca.warehouse.repository import WarehouseRepository


def forecast_daily_spend(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    horizon: int = 30,
    interval: float = 0.8,
    metric: str = "billed_cost",
    service: str | None = None,
) -> Forecast:
    """Forecast daily spend `horizon` days past the history window [start, end)."""
    params: dict = {"start": start, "end": end, "metric": metric}
    if service:
        params["service"] = service
    result = run_query(repo, "daily_spend", params)
    history = [(row["day"], float(row["amount"])) for row in result.rows]
    return forecast_series(history, horizon=horizon, interval=interval, metric=metric)
