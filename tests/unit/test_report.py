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


def test_render_handles_empty_months() -> None:
    data = {**_DATA, "months": []}
    html = render_html(data)
    assert "<!doctype html>" in html  # does not crash on no history
