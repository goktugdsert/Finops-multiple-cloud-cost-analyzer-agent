"""Generate a self-contained HTML spend report (KPIs, top services, trend + forecast).

Every number is pulled from the fixed query layer and the forecaster, so the report is
fully grounded and reproducible — no LLM, no live figure invented. `render_html` is a pure
function of a data dict, so it is unit-testable without a database.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from html import escape
from typing import Any

from mcca.config import get_settings
from mcca.forecasting.service import forecast_daily_spend
from mcca.logging import configure_logging
from mcca.queries.registry import run_query
from mcca.warehouse.postgres import PostgresRepository


def _f(value: Any) -> float:
    return float(value) if value is not None else 0.0


def _money(value: Any) -> str:
    return f"${_f(value):,.2f}"


def build_report_data(
    repo: Any, start: date, end: date, *, horizon: int = 30, top_n: int = 8
) -> dict[str, Any]:
    """Gather all report figures from queries + the forecaster (grounded)."""
    window = {"start": start, "end": end}
    total = run_query(repo, "total_spend", window).rows[0]
    services = run_query(
        repo, "spend_by_service", {**window, "limit": top_n, "charge_category": "Usage"}
    ).rows
    mom = run_query(repo, "month_over_month", window).rows
    forecast = forecast_daily_spend(repo, start, end, horizon=horizon)

    billed, effective = _f(total["billed_cost"]), _f(total["effective_cost"])
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "total_billed": billed,
        "total_effective": effective,
        "savings": billed - effective,
        "services": [{"name": r["service_name"], "amount": _f(r["amount"])} for r in services],
        "months": [
            {
                "label": r["month"].strftime("%b %Y"),
                "amount": _f(r["amount"]),
                "delta_pct": None if r["delta_pct"] is None else _f(r["delta_pct"]),
            }
            for r in mom
        ],
        "forecast": {
            "model": forecast.model,
            "horizon": forecast.horizon,
            "interval": forecast.interval,
            "mid": sum(_f(p.yhat) for p in forecast.points),
            "lo": sum(_f(p.lower) for p in forecast.points),
            "hi": sum(_f(p.upper) for p in forecast.points),
        },
    }


def _svg_trend(months: list[dict[str, Any]], forecast: dict[str, Any]) -> str:
    """A compact monthly-trend line with the forecast point + 80% whisker."""
    if not months:
        return ""
    w, h, pad = 680, 210, 44
    series = [m["amount"] for m in months]
    lo, hi, mid = forecast["lo"], forecast["hi"], forecast["mid"]
    n = len(months) + 1
    vmax = max([*series, hi]) * 1.08
    vmin = min([*series, lo]) * 0.92
    if vmax == vmin:
        vmax = vmin + 1

    def px(i: int) -> float:
        return pad + i * ((w - 2 * pad) / max(1, n - 1))

    def py(v: float) -> float:
        return h - pad - (v - vmin) / (vmax - vmin) * (h - 2 * pad)

    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Spend trend">']
    parts.append(
        f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#d0d7de"/>'
    )
    line = " ".join(f"{px(i):.1f},{py(m['amount']):.1f}" for i, m in enumerate(months))
    parts.append(f'<polyline fill="none" stroke="#2563eb" stroke-width="2.5" points="{line}"/>')
    for i, m in enumerate(months):
        parts.append(f'<circle cx="{px(i):.1f}" cy="{py(m["amount"]):.1f}" r="3" fill="#2563eb"/>')
        parts.append(
            f'<text x="{px(i):.1f}" y="{h - pad + 16}" font-size="10" text-anchor="middle" '
            f'fill="#57606a">{escape(m["label"])}</text>'
        )
    fx = px(n - 1)
    # dashed connector history -> forecast
    parts.append(
        f'<line x1="{px(n - 2):.1f}" y1="{py(months[-1]["amount"]):.1f}" x2="{fx:.1f}" '
        f'y2="{py(mid):.1f}" stroke="#f59e0b" stroke-width="2" stroke-dasharray="5 4"/>'
    )
    # 80% uncertainty whisker
    parts.append(
        f'<line x1="{fx:.1f}" y1="{py(lo):.1f}" x2="{fx:.1f}" y2="{py(hi):.1f}" '
        f'stroke="#f59e0b" stroke-width="2"/>'
    )
    for v in (lo, hi):
        parts.append(
            f'<line x1="{fx - 5:.1f}" y1="{py(v):.1f}" x2="{fx + 5:.1f}" y2="{py(v):.1f}" '
            f'stroke="#f59e0b" stroke-width="2"/>'
        )
    parts.append(f'<circle cx="{fx:.1f}" cy="{py(mid):.1f}" r="4" fill="#f59e0b"/>')
    parts.append(
        f'<text x="{fx:.1f}" y="{h - pad + 16}" font-size="10" text-anchor="middle" '
        f'fill="#b45309">Forecast</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;
background:#f6f8fa;color:#1f2328}
.wrap{max-width:900px;margin:0 auto;padding:32px}
h1{font-size:22px;margin:0 0 4px}.sub{color:#57606a;font-size:13px;margin-bottom:24px}
.cards{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px}
.card{flex:1;min-width:180px;background:#fff;border:1px solid #d0d7de;
border-radius:10px;padding:16px}
.card .k{color:#57606a;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.card .v{font-size:22px;font-weight:600;margin-top:6px}
.card .n{font-size:12px;color:#57606a;margin-top:4px}
.panel{background:#fff;border:1px solid #d0d7de;border-radius:10px;padding:20px;margin-bottom:24px}
.panel h2{font-size:15px;margin:0 0 14px}
.bar-row{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}
.bar-row .name{width:230px;color:#1f2328}.bar-row .amt{width:96px;text-align:right;color:#57606a}
.bar{flex:1;height:14px;background:#eaeef2;border-radius:7px;overflow:hidden}
.bar>span{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid #eaeef2}
th:first-child,td:first-child{text-align:left}
.up{color:#cf222e}.down{color:#1a7f37}
.foot{color:#8b949e;font-size:11px;margin-top:8px}
"""


def render_html(data: dict[str, Any]) -> str:
    """Render the report HTML from a data dict (pure function)."""
    fc = data["forecast"]
    services = data["services"]
    max_amt = max((s["amount"] for s in services), default=1.0) or 1.0

    cards = [
        ("Total billed", _money(data["total_billed"]), f"{data['start']} to {data['end']}"),
        ("Effective (amortized)", _money(data["total_effective"]), "after RI/SP amortization"),
        ("Commitment savings", _money(data["savings"]), "billed − effective"),
        (
            f"Forecast next {fc['horizon']}d",
            _money(fc["mid"]),
            f"{int(fc['interval'] * 100)}% range {_money(fc['lo'])}–{_money(fc['hi'])}",
        ),
    ]
    card_html = "".join(
        f'<div class="card"><div class="k">{escape(k)}</div>'
        f'<div class="v">{escape(v)}</div><div class="n">{escape(n)}</div></div>'
        for k, v, n in cards
    )

    bars = "".join(
        f'<div class="bar-row"><div class="name">{escape(s["name"])}</div>'
        f'<div class="bar"><span style="width:{s["amount"] / max_amt * 100:.1f}%"></span></div>'
        f'<div class="amt">{_money(s["amount"])}</div></div>'
        for s in services
    )

    rows = []
    for m in data["months"]:
        if m["delta_pct"] is None:
            delta = "—"
        else:
            cls = "up" if m["delta_pct"] > 0 else "down"
            delta = f'<span class="{cls}">{m["delta_pct"]:+.1f}%</span>'
        rows.append(
            f"<tr><td>{escape(m['label'])}</td><td>{_money(m['amount'])}</td><td>{delta}</td></tr>"
        )
    mom_table = "".join(rows)

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Cloud Cost Report</title><style>{_CSS}</style></head><body><div class='wrap'>"
        "<h1>Multi-Cloud Cost Report</h1>"
        f"<div class='sub'>AWS • {escape(data['start'])} to {escape(data['end'])} "
        f"• generated {escape(data['generated'])}</div>"
        f"<div class='cards'>{card_html}</div>"
        f"<div class='panel'><h2>Monthly trend &amp; forecast</h2>"
        f"{_svg_trend(data['months'], fc)}"
        f"<div class='foot'>Forecast model: {escape(fc['model'])} · orange whisker = "
        f"{int(fc['interval'] * 100)}% prediction interval</div></div>"
        f"<div class='panel'><h2>Top services by usage cost</h2>{bars}</div>"
        f"<div class='panel'><h2>Month over month</h2>"
        f"<table><thead><tr><th>Month</th><th>Billed</th><th>Δ vs prior</th></tr></thead>"
        f"<tbody>{mom_table}</tbody></table></div>"
        "<div class='foot'>Every figure is produced by a validated query or the forecaster — "
        "never by a language model.</div>"
        "</div></body></html>"
    )


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _minus_months(d: date, months: int) -> date:
    total = (d.year * 12 + (d.month - 1)) - months
    return date(total // 12, total % 12 + 1, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an HTML cloud cost report.")
    parser.add_argument("--months", type=int, default=9, help="History window in months.")
    parser.add_argument("--horizon", type=int, default=30, help="Forecast horizon in days.")
    parser.add_argument("--out", default="report.html", help="Output HTML path.")
    args = parser.parse_args()

    configure_logging()
    get_settings()
    repo = PostgresRepository()
    end = _first_of_month(date.today())
    start = _minus_months(end, args.months)
    data = build_report_data(repo, start, end, horizon=args.horizon)
    html = render_html(data)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Wrote {args.out} ({len(html):,} bytes) covering {start} to {end}.")


if __name__ == "__main__":
    main()
