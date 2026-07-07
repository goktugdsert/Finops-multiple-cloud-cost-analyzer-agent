"""Deterministic cost detectors: spikes and steady structural spend.

Both operate on a daily (date, service, amount) history:

- `detect_spikes` flags days where a service's spend jumps far above its own trailing
  baseline — using BOTH a z-score (`> mean + z*std`) and a ratio floor (`>= min_ratio *
  mean`), so tiny fluctuations on flat series don't trigger false positives.
- `detect_steady_costs` flags services whose spend is flat and persistent (low coefficient
  of variation, ~no growth) — the signature of structural cost (e.g. idle/oversized
  resources) worth a review. We call these candidates honestly: without utilization
  metrics we cannot *prove* waste, only that the spend is steady.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np

_CENTS = Decimal("0.01")


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Spike:
    date: date
    service: str
    amount: Decimal
    baseline: Decimal
    ratio: float  # amount / baseline


@dataclass(frozen=True)
class SteadyCost:
    service: str
    mean_daily: Decimal
    monthly_estimate: Decimal
    cov: float  # coefficient of variation (std/mean)
    growth_ratio: float  # total drift over the window relative to the mean


@dataclass(frozen=True)
class DetectionReport:
    window: int
    z: float
    spikes: list[Spike]
    steady_costs: list[SteadyCost]


def _series_by_service(rows: list[dict[str, Any]]) -> dict[str, list[tuple[date, float]]]:
    grouped: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in rows:
        grouped[row["service_name"]].append((row["day"], float(row["amount"])))
    for service in grouped:
        grouped[service].sort()
    return grouped


def detect_spikes(
    rows: list[dict[str, Any]],
    *,
    window: int = 14,
    z: float = 3.0,
    min_ratio: float = 1.5,
    min_amount: float = 1.0,
) -> list[Spike]:
    """Flag per-service days that exceed the trailing baseline by z-score AND ratio."""
    spikes: list[Spike] = []
    for service, series in _series_by_service(rows).items():
        values = [v for _, v in series]
        days = [d for d, _ in series]
        for i in range(window, len(values)):
            base = np.array(values[i - window : i], dtype=float)
            mean = float(base.mean())
            std = float(base.std(ddof=1)) if len(base) > 1 else 0.0
            value = values[i]
            if (
                mean > 0
                and value >= min_amount
                and value > mean + z * std
                and value >= min_ratio * mean
            ):
                spikes.append(Spike(days[i], service, _money(value), _money(mean), value / mean))
    spikes.sort(key=lambda s: s.ratio, reverse=True)
    return spikes


def detect_steady_costs(
    rows: list[dict[str, Any]],
    *,
    max_cov: float = 0.08,
    max_growth_ratio: float = 0.15,
    min_monthly: float = 20.0,
    min_days: int = 14,
) -> list[SteadyCost]:
    """Flag services with flat, persistent spend (low variation, ~no growth)."""
    steady: list[SteadyCost] = []
    for service, series in _series_by_service(rows).items():
        values = np.array([v for _, v in series], dtype=float)
        if len(values) < min_days:
            continue
        mean = float(values.mean())
        if mean <= 0:
            continue
        cov = float(values.std(ddof=1) / mean)
        x = np.arange(len(values))
        slope = float(np.polyfit(x, values, 1)[0])
        growth_ratio = abs(slope * len(values)) / mean
        monthly = mean * 30
        if cov <= max_cov and growth_ratio <= max_growth_ratio and monthly >= min_monthly:
            steady.append(
                SteadyCost(
                    service, _money(mean), _money(monthly), round(cov, 4), round(growth_ratio, 4)
                )
            )
    steady.sort(key=lambda s: s.monthly_estimate, reverse=True)
    return steady
