"""The report renders grounded figures into self-contained HTML (pure, no DB)."""

from __future__ import annotations

from mcca.surface.report import render_html

_DATA = {
    "start": "2026-01-01",
    "end": "2026-04-01",
    "generated": "2026-04-01 00:00 UTC",
    "total_billed": 24000.0,
    "total_effective": 20000.0,
    "savings": 4000.0,
    "services": [
        {"name": "Amazon Elastic Compute Cloud - Compute", "amount": 12000.0},
        {"name": "Amazon Relational Database Service", "amount": 5000.0},
    ],
    "providers": [
        {"name": "AWS", "amount": 18000.0},
        {"name": "Azure", "amount": 6000.0},
    ],
    "teams": [
        {"name": "platform", "amount": 15000.0},
        {"name": "data", "amount": 8000.0},
        {"name": "unattributed", "amount": 1000.0},
    ],
    "drivers": {
        "period": "Mar 2026",
        "total_delta": 500.0,
        "items": [
            {"service": "Amazon EC2", "delta": 300.0, "current": 8000.0},
            {"service": "AWS Lambda", "delta": -50.0, "current": 400.0},
        ],
    },
    "findings": [
        {
            "kind": "SPIKE",
            "severity": "HIGH",
            "owner": "alice",
            "team": "platform",
            "summary": "Amazon EC2 spend spiked 4.6x on 2026-01-04.",
            "recommendation": "Investigate the Amazon EC2 spike.",
        }
    ],
    "months": [
        {"label": "Jan 2026", "amount": 7800.0, "delta_pct": None},
        {"label": "Feb 2026", "amount": 8200.0, "delta_pct": 5.1},
        {"label": "Mar 2026", "amount": 8000.0, "delta_pct": -2.4},
    ],
    "forecast": {
        "model": "SARIMAX(1,1,1)(1,1,1,7)",
        "horizon": 30,
        "interval": 0.8,
        "mid": 8300.0,
        "lo": 7000.0,
        "hi": 9600.0,
    },
    "anomalies": {
        "spikes": [
            {"date": "2026-02-08", "service": "AWS Data Transfer", "amount": 900.0, "ratio": 6.0}
        ],
        "steady": [{"service": "Amazon Elastic Block Store", "monthly_estimate": 120.0}],
    },
    "budget": {
        "month": "Jul 2026",
        "status": "OVER",
        "budget": 9000.0,
        "actual": 0.0,
        "projected": 10500.0,
        "projected_lo": 9000.0,
        "projected_hi": 12000.0,
        "variance": 1500.0,
        "variance_pct": 16.7,
    },
}


def test_render_html_is_self_contained_and_grounded() -> None:
    html = render_html(_DATA)
    assert html.startswith("<!doctype html>")
    assert "<style>" in html and "<svg" in html  # inline CSS + chart, no external assets
    # Key grounded figures and labels are present.
    assert "$24,000.00" in html
    assert "Amazon Elastic Compute Cloud - Compute" in html
    assert "SARIMAX(1,1,1)(1,1,1,7)" in html
    assert "never by a language model" in html
    # Detection panel is present with the flagged spike + steady-cost service.
    assert "Detected anomalies" in html
    assert "AWS Data Transfer" in html
    assert "Amazon Elastic Block Store" in html
    # Budget panel with status.
    assert "Budget — Jul 2026" in html
    assert "Over budget" in html
    # Attribution + explain-why panels.
    assert "Spend by team (attribution)" in html
    assert "platform" in html
    assert "What changed — Mar 2026" in html
    # Routing panel with owner + recommendation.
    assert "Recommended actions" in html
    assert "alice" in html
    assert "Recommend-only" in html
    # Multi-cloud: provider panel + subtitle lists both clouds.
    assert "Spend by cloud provider" in html
    assert "AWS + Azure" in html


def test_render_handles_empty_months() -> None:
    data = {**_DATA, "months": []}
    html = render_html(data)
    assert "<!doctype html>" in html  # does not crash on no history
