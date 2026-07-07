"""Detectors flag a clear spike and flat structural spend, and ignore normal growth."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from mcca.detection.detector import detect_spikes, detect_steady_costs


def _rows() -> list[dict]:
    start = date(2026, 1, 1)
    rows: list[dict] = []
    for i in range(30):
        day = start + timedelta(days=i)
        # SPIKY: flat ~100, one 4x jump on day 20.
        rows.append(
            {"day": day, "service_name": "SPIKY", "amount": Decimal("400" if i == 20 else "100")}
        )
        # FLAT: constant 50 -> steady structural spend.
        rows.append({"day": day, "service_name": "FLAT", "amount": Decimal("50")})
        # GROW: steadily rising -> neither a spike nor steady.
        rows.append({"day": day, "service_name": "GROW", "amount": Decimal(str(10 + 8 * i))})
    return rows


def test_detects_the_spike_only() -> None:
    spikes = detect_spikes(_rows(), window=14)
    spiky = [s for s in spikes if s.service == "SPIKY"]
    assert len(spiky) == 1
    assert spiky[0].date == date(2026, 1, 21)  # day index 20
    assert spiky[0].ratio > 3.5
    # The flat service never spikes.
    assert not any(s.service == "FLAT" for s in spikes)


def test_detects_flat_structural_spend_only() -> None:
    steady = detect_steady_costs(_rows())
    services = {c.service for c in steady}
    assert "FLAT" in services
    assert "GROW" not in services  # growth excludes it
    flat = next(c for c in steady if c.service == "FLAT")
    assert flat.monthly_estimate == Decimal("1500.00")  # 50/day * 30
    assert flat.cov < 0.01
