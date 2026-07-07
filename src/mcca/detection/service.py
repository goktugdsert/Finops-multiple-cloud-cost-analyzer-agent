"""Detection orchestration: pull grounded day x service history, run the detectors."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from mcca.detection.detector import DetectionReport, detect_spikes, detect_steady_costs
from mcca.queries.registry import run_query

if TYPE_CHECKING:
    from mcca.warehouse.repository import WarehouseRepository


def detect(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    metric: str = "billed_cost",
    window: int = 14,
    z: float = 3.0,
) -> DetectionReport:
    """Detect spikes and steady structural spend over [start, end) from usage lines."""
    rows = run_query(
        repo,
        "daily_spend_by_service",
        {"start": start, "end": end, "metric": metric, "charge_category": "Usage"},
    ).rows
    return DetectionReport(
        window=window,
        z=z,
        spikes=detect_spikes(rows, window=window, z=z),
        steady_costs=detect_steady_costs(rows),
    )
