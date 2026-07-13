"""Generate a self-contained HTML spend report (KPIs, top services, trend + forecast).

Every number is pulled from the fixed query layer and the forecaster, so the report is
fully grounded and reproducible — no LLM, no live figure invented. `render_html` is a pure
function of a data dict, so it is unit-testable without a database.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from html import escape
from typing import Any

from mcca.analysis.drivers import explain_change
from mcca.budgets.service import spend_vs_budget
from mcca.config import get_settings
from mcca.detection.service import detect
from mcca.forecasting.service import forecast_daily_spend
from mcca.governance.service import evaluate_policies
from mcca.logging import configure_logging
from mcca.optimization.service import review_recommendations
from mcca.queries.registry import run_query
from mcca.routing.router import route
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
    detection = detect(repo, start, end)
    # Project the current month (the month starting at `end`) against the budget.
    bs = spend_vs_budget(repo, end)
    teams = run_query(repo, "spend_by_team", window).rows
    # Explain the last full month vs the calendar month before it.
    last_month = _minus_months(end, 1)
    prior_month = _minus_months(end, 2)
    drivers = explain_change(
        repo, last_month, end, prior_start=prior_month, prior_end=last_month, top_n=5
    )
    routing = route(repo, start, end, budget_month=end)
    policy_violations = evaluate_policies(repo, start, end)
    review = review_recommendations(repo, start, end)
    providers = run_query(repo, "spend_by_provider", window).rows
    # Recent daily history (tail of the window) so the forecast chart is a continuous
    # daily curve, not just an aggregate — grounded in the daily_spend query.
    tail_start = max(start, _minus_months(end, 2))
    daily = run_query(repo, "daily_spend", {"start": tail_start, "end": end}).rows

    billed, effective = _f(total["billed_cost"]), _f(total["effective_cost"])
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "total_billed": billed,
        "total_effective": effective,
        "savings": billed - effective,
        "services": [{"name": r["service_name"], "amount": _f(r["amount"])} for r in services],
        "providers": [{"name": r["provider_name"], "amount": _f(r["amount"])} for r in providers],
        "teams": [{"name": r["x_team"], "amount": _f(r["amount"])} for r in teams],
        "drivers": {
            "period": last_month.strftime("%b %Y"),
            "total_delta": _f(drivers.total_delta),
            "items": [
                {"service": d.service, "delta": _f(d.delta), "current": _f(d.current)}
                for d in drivers.drivers
            ],
        },
        "months": [
            {
                "label": r["month"].strftime("%b %Y"),
                "amount": _f(r["amount"]),
                "delta_pct": None if r["delta_pct"] is None else _f(r["delta_pct"]),
            }
            for r in mom
        ],
        "daily": [{"date": r["day"].isoformat(), "amount": _f(r["amount"])} for r in daily],
        "forecast": {
            "model": forecast.model,
            "horizon": forecast.horizon,
            "interval": forecast.interval,
            "mid": sum(_f(p.yhat) for p in forecast.points),
            "lo": sum(_f(p.lower) for p in forecast.points),
            "hi": sum(_f(p.upper) for p in forecast.points),
            "points": [
                {
                    "date": p.date.isoformat(),
                    "yhat": _f(p.yhat),
                    "lo": _f(p.lower),
                    "hi": _f(p.upper),
                }
                for p in forecast.points
            ],
        },
        "budget": None
        if bs is None
        else {
            "month": bs.month.strftime("%b %Y"),
            "status": bs.status,
            "budget": _f(bs.budget_amount),
            "actual": _f(bs.actual),
            "projected": _f(bs.projected),
            "projected_lo": _f(bs.projected_lo),
            "projected_hi": _f(bs.projected_hi),
            "variance": _f(bs.variance),
            "variance_pct": round(bs.variance_pct, 1),
        },
        "anomalies": {
            "spikes": [
                {
                    "date": s.date.isoformat(),
                    "service": s.service,
                    "amount": _f(s.amount),
                    "ratio": round(s.ratio, 1),
                }
                for s in detection.spikes[:5]
            ],
            "steady": [
                {"service": c.service, "monthly_estimate": _f(c.monthly_estimate)}
                for c in detection.steady_costs[:5]
            ],
        },
        "findings": [
            {
                "kind": f.kind,
                "severity": f.severity,
                "owner": f.owner,
                "team": f.team,
                "summary": f.summary,
                "recommendation": f.recommendation,
            }
            for f in routing.findings[:6]
        ],
        "policy": [
            {"severity": v.severity, "summary": v.summary, "recommendation": v.recommendation}
            for v in policy_violations
        ],
        "recommendations": [
            {
                "key": r.key,
                "severity": r.severity,
                "summary": r.summary,
                "action": r.action,
                "status": r.status,
            }
            for r in review.recommendations
        ],
    }


# Categorical palette slots (identity encoding) — validated light/dark hues, fixed order.
_CAT = ("var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)")


def _short_date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%b %d")


def _svg_forecast_area(
    daily: list[dict[str, Any]], points: list[dict[str, Any]], interval: float
) -> str:
    """Daily spend history flowing into the forecast, with a shaded uncertainty band."""
    if not daily or not points:
        return ""
    w, h = 760, 280
    pl, pr, pt, pb = 56, 18, 16, 34
    hist = [d["amount"] for d in daily]
    fy = [p["yhat"] for p in points]
    flo = [p["lo"] for p in points]
    fhi = [p["hi"] for p in points]
    hi_pts, m = len(daily), len(points)
    n = hi_pts + m
    vmax = max([*hist, *fhi]) * 1.06
    vmin = min([*hist, *flo]) * 0.94
    if vmax <= vmin:
        vmax = vmin + 1

    def px(i: float) -> float:
        return pl + i * ((w - pl - pr) / max(1, n - 1))

    def py(v: float) -> float:
        return h - pb - (v - vmin) / (vmax - vmin) * (h - pt - pb)

    p = [
        f'<svg id="fc-chart" viewBox="0 0 {w} {h}" width="100%" role="img" '
        'aria-label="Daily spend history and forecast">'
    ]
    # Recessive gridlines + tabular y labels.
    for t in range(5):
        v = vmin + (vmax - vmin) * t / 4
        y = py(v)
        p.append(
            f'<line x1="{pl}" y1="{y:.1f}" x2="{w - pr}" y2="{y:.1f}" '
            'style="stroke:var(--grid)" stroke-width="1"/>'
        )
        p.append(
            f'<text x="{pl - 8}" y="{y + 3:.1f}" text-anchor="end" font-size="10" '
            f'style="fill:var(--muted)" font-variant-numeric="tabular-nums">${v / 1000:.1f}k</text>'
        )
    # Uncertainty band (lo..hi across the forecast region).
    top = [f"{px(hi_pts + i):.1f},{py(fhi[i]):.1f}" for i in range(m)]
    bot = [f"{px(hi_pts + i):.1f},{py(flo[i]):.1f}" for i in reversed(range(m))]
    p.append(f'<polygon points="{" ".join(top + bot)}" style="fill:var(--band)"/>')
    # History line (solid) then forecast line (dashed), joined at the boundary.
    hline = " ".join(f"{px(i):.1f},{py(hist[i]):.1f}" for i in range(hi_pts))
    p.append(f'<polyline fill="none" style="stroke:var(--s1)" stroke-width="2" points="{hline}"/>')
    fline = [f"{px(hi_pts - 1):.1f},{py(hist[-1]):.1f}"]
    fline += [f"{px(hi_pts + i):.1f},{py(fy[i]):.1f}" for i in range(m)]
    p.append(
        f'<polyline fill="none" style="stroke:var(--s1)" stroke-width="2" '
        f'stroke-dasharray="5 4" points="{" ".join(fline)}"/>'
    )
    # Boundary divider (history | forecast).
    bx = (px(hi_pts - 1) + px(hi_pts)) / 2
    p.append(
        f'<line x1="{bx:.1f}" y1="{pt}" x2="{bx:.1f}" y2="{h - pb}" '
        'style="stroke:var(--axis)" stroke-width="1" stroke-dasharray="3 3"/>'
    )
    p.append(
        f'<text x="{bx + 4:.1f}" y="{pt + 10}" font-size="10" '
        'style="fill:var(--muted)">forecast &rarr;</text>'
    )
    # Endpoint marker + direct label (with a native hover tooltip).
    ex, ey = px(n - 1), py(fy[-1])
    p.append(
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" style="fill:var(--s1)"><title>'
        f"Projected {_short_date(points[-1]['date'])}: ${fy[-1]:,.0f} "
        f"({int(interval * 100)}% range ${flo[-1]:,.0f}-${fhi[-1]:,.0f})</title></circle>"
    )
    p.append(
        f'<text x="{ex - 6:.1f}" y="{ey - 8:.1f}" text-anchor="end" font-size="10" '
        f'font-weight="600" style="fill:var(--s1)">${fy[-1]:,.0f}/day</text>'
    )
    # X labels: first, boundary, last.
    for i, lab, anchor in (
        (0, daily[0]["date"], "start"),
        (hi_pts, points[0]["date"], "middle"),
        (n - 1, points[-1]["date"], "end"),
    ):
        p.append(
            f'<text x="{px(i):.1f}" y="{h - pb + 16:.1f}" text-anchor="{anchor}" font-size="10" '
            f'style="fill:var(--muted)">{_short_date(lab)}</text>'
        )
    # Hover layer: a crosshair + focus dot the script moves, and a transparent capture rect
    # spanning the plot area (kept last so it receives the pointer events).
    p.append(f'<line class="fc-cross" x1="{pl}" y1="{pt}" x2="{pl}" y2="{h - pb}"/>')
    p.append(f'<circle class="fc-focus" cx="{pl}" cy="{pt}" r="4.5"/>')
    p.append(
        f'<rect class="fc-hit" x="{pl}" y="{pt}" width="{w - pl - pr}" height="{h - pt - pb}"/>'
    )
    p.append("</svg>")

    # Per-day data for the tooltip (viewBox coords + label + value + band), embedded inline.
    marks: list[dict[str, Any]] = []
    for i in range(hi_pts):
        marks.append(
            {
                "x": round(px(i), 1),
                "y": round(py(hist[i]), 1),
                "l": _short_date(daily[i]["date"]),
                "v": round(hist[i]),
                "k": "a",
            }
        )
    for i in range(m):
        marks.append(
            {
                "x": round(px(hi_pts + i), 1),
                "y": round(py(fy[i]), 1),
                "l": _short_date(points[i]["date"]),
                "v": round(fy[i]),
                "k": "f",
                "lo": round(flo[i]),
                "hi": round(fhi[i]),
            }
        )
    p.append('<div id="fc-tip" class="fc-tip"></div>')
    js = (
        _FORECAST_JS.replace("__PTS__", json.dumps(marks))
        .replace("__PCT__", str(int(interval * 100)))
        .replace("__W__", str(w))
        .replace("__H__", str(h))
    )
    p.append(f"<script>{js}</script>")
    return "".join(p)


# Hover interaction for the forecast chart: on pointer move over the plot, snap to the
# nearest day, move the crosshair + focus dot, and show a tooltip with that day's value
# (and the prediction band for forecast days). Pure client JS, no external libraries.
_FORECAST_JS = (
    "(function(){var s=document.getElementById('fc-chart');if(!s)return;"
    "var pts=__PTS__,pct=__PCT__,W=__W__,H=__H__;"
    "var cr=s.querySelector('.fc-cross'),fo=s.querySelector('.fc-focus'),"
    "hit=s.querySelector('.fc-hit'),tip=document.getElementById('fc-tip');"
    "function fmt(x){return x.toLocaleString('en-US');}"
    "function tog(o){var v=o?'1':'0';cr.style.opacity=v;fo.style.opacity=v;"
    "tip.style.display=o?'block':'none';}"
    "function mv(e){var r=s.getBoundingClientRect();var fx=(e.clientX-r.left)/r.width*W;"
    "var b=pts[0],bd=1e9,i;for(i=0;i<pts.length;i++){var d=Math.abs(pts[i].x-fx);"
    "if(d<bd){bd=d;b=pts[i];}}"
    "cr.setAttribute('x1',b.x);cr.setAttribute('x2',b.x);"
    "fo.setAttribute('cx',b.x);fo.setAttribute('cy',b.y);tog(true);"
    "var t='<b>'+b.l+'</b><br>'+(b.k==='f'?'forecast ':'')+'$'+fmt(b.v)+'/day';"
    "if(b.k==='f'){t+='<br><span class=\"fc-muted\">'+pct+'%: $'+fmt(b.lo)+'-$'+fmt(b.hi)"
    "+'</span>';}tip.innerHTML=t;"
    "var lx=b.x/W*r.width,ly=b.y/H*r.height;"
    "tip.style.left=Math.max(4,Math.min(r.width-152,lx+12))+'px';"
    "tip.style.top=Math.max(4,ly-10)+'px';}"
    "hit.addEventListener('mousemove',mv);"
    "hit.addEventListener('mouseleave',function(){tog(false);});"
    "hit.addEventListener('touchstart',function(e){mv(e.touches[0]);},{passive:true});"
    "hit.addEventListener('touchmove',function(e){mv(e.touches[0]);},{passive:true});"
    "})();"
)


def _svg_trend(months: list[dict[str, Any]], forecast: dict[str, Any]) -> str:
    """Fallback compact monthly-trend line + forecast whisker (used when no daily series)."""
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
        f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" '
        'style="stroke:var(--grid)"/>'
    )
    line = " ".join(f"{px(i):.1f},{py(m['amount']):.1f}" for i, m in enumerate(months))
    parts.append(
        f'<polyline fill="none" style="stroke:var(--s1)" stroke-width="2.5" points="{line}"/>'
    )
    for i, mm in enumerate(months):
        parts.append(
            f'<circle cx="{px(i):.1f}" cy="{py(mm["amount"]):.1f}" r="3" style="fill:var(--s1)"/>'
        )
        parts.append(
            f'<text x="{px(i):.1f}" y="{h - pad + 16}" font-size="10" text-anchor="middle" '
            f'style="fill:var(--muted)">{escape(mm["label"])}</text>'
        )
    fx = px(n - 1)
    parts.append(
        f'<line x1="{px(n - 2):.1f}" y1="{py(months[-1]["amount"]):.1f}" x2="{fx:.1f}" '
        f'y2="{py(mid):.1f}" style="stroke:var(--s3)" stroke-width="2" stroke-dasharray="5 4"/>'
    )
    parts.append(
        f'<line x1="{fx:.1f}" y1="{py(lo):.1f}" x2="{fx:.1f}" y2="{py(hi):.1f}" '
        f'style="stroke:var(--s3)" stroke-width="2"/>'
    )
    for v in (lo, hi):
        parts.append(
            f'<line x1="{fx - 5:.1f}" y1="{py(v):.1f}" x2="{fx + 5:.1f}" y2="{py(v):.1f}" '
            f'style="stroke:var(--s3)" stroke-width="2"/>'
        )
    parts.append(f'<circle cx="{fx:.1f}" cy="{py(mid):.1f}" r="4" style="fill:var(--s3)"/>')
    parts.append(
        f'<text x="{fx:.1f}" y="{h - pad + 16}" font-size="10" text-anchor="middle" '
        f'style="fill:var(--muted)">Forecast</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _cat_bars(items: list[dict[str, Any]]) -> str:
    """Horizontal bars colored per entity (identity) — for providers/teams."""
    maxv = max((it["amount"] for it in items), default=1.0) or 1.0
    return "".join(
        f'<div class="brow"><span class="bname" title="{escape(it["name"])}">'
        f'{escape(it["name"])}</span><span class="btrack"><span class="bfill" '
        f'style="width:{it["amount"] / maxv * 100:.1f}%;background:{_CAT[i % len(_CAT)]}"></span>'
        f'</span><span class="bamt">{_money(it["amount"])}</span></div>'
        for i, it in enumerate(items)
    )


def _mag_bars(items: list[dict[str, Any]]) -> str:
    """Horizontal bars in one hue (magnitude) — for ranked service spend."""
    maxv = max((it["amount"] for it in items), default=1.0) or 1.0
    return "".join(
        f'<div class="brow"><span class="bname" title="{escape(it["name"])}">'
        f'{escape(it["name"])}</span><span class="btrack"><span class="bfill" '
        f'style="width:{it["amount"] / maxv * 100:.1f}%;background:var(--s1)"></span></span>'
        f'<span class="bamt">{_money(it["amount"])}</span></div>'
        for it in items
    )


_CSS = """
*{box-sizing:border-box}
:root{
--plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#1baf7a;--s3:#eda100;--s4:#008300;--s5:#4a3aa7;--s6:#e34948;
--band:rgba(42,120,214,.15);--good:#0ca30c;--serious:#ec835a;--crit:#d03b3b;
--shadow:0 1px 2px rgba(11,11,11,.04),0 4px 18px rgba(11,11,11,.05)}
@media (prefers-color-scheme:dark){:root{
--plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#199e70;--s3:#c98500;--s4:#008300;--s5:#9085e9;--s6:#e66767;
--band:rgba(57,135,229,.22);--good:#0ca30c;--serious:#ec835a;--crit:#e05656;
--shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.4)}}
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:0;
background:var(--plane);color:var(--ink);-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:28px 24px 56px}
.hd{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:22px}
h1{font-size:22px;font-weight:650;margin:0;letter-spacing:-.01em}
.sub{color:var(--ink2);font-size:12.5px;margin-top:5px}
.live{font-size:11px;color:var(--good);font-weight:600;white-space:nowrap;padding-top:4px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:18px}
.tile{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--s1);
border-radius:13px;padding:15px 16px;box-shadow:var(--shadow)}
.tile .k{color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase;
letter-spacing:.05em}
.tile .v{font-size:25px;font-weight:650;margin-top:7px;letter-spacing:-.02em}
.tile .n{font-size:11.5px;color:var(--ink2);margin-top:4px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;
padding:18px 20px;margin-bottom:18px;box-shadow:var(--shadow)}
.card-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:10px}
.card h2{font-size:14px;font-weight:640;margin:0}
.tag{font-size:11px;color:var(--ink2);background:var(--plane);border:1px solid var(--border);
padding:2px 9px;border-radius:20px;white-space:nowrap}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media (max-width:720px){.grid2{grid-template-columns:1fr}}
.chart{position:relative;margin:2px -4px}
.fc-cross{stroke:var(--axis);stroke-width:1;stroke-dasharray:3 3;opacity:0;pointer-events:none}
.fc-focus{fill:var(--s1);stroke:var(--surface);stroke-width:1.5;opacity:0;pointer-events:none}
.fc-hit{fill:transparent;cursor:crosshair}
.fc-tip{position:absolute;display:none;pointer-events:none;z-index:6;white-space:nowrap;
transform:translateY(-100%);background:var(--surface);color:var(--ink);
border:1px solid var(--border);border-radius:8px;padding:6px 9px;font-size:11.5px;
line-height:1.45;box-shadow:var(--shadow);font-variant-numeric:tabular-nums}
.fc-muted{color:var(--muted)}
.brow{display:flex;align-items:center;gap:12px;margin:9px 0;font-size:13px}
.bname{width:210px;flex:none;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btrack{flex:1;height:11px;background:var(--grid);border-radius:6px;overflow:hidden}
.bfill{display:block;height:100%;border-radius:6px}
.bamt{width:100px;flex:none;text-align:right;color:var(--ink2);font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:right;padding:8px;border-bottom:1px solid var(--border);
font-variant-numeric:tabular-nums}
th{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;font-weight:600}
th:first-child,td:first-child{text-align:left;font-variant-numeric:normal}
.up{color:var(--crit)}.down{color:var(--good)}
.foot{color:var(--muted);font-size:11px;margin-top:10px}
.badge{font-size:11px;padding:3px 10px;border-radius:20px;font-weight:600;white-space:nowrap;
display:inline-flex;align-items:center;gap:6px;background:var(--plane);
border:1px solid var(--border);color:var(--ink)}
.dot{width:8px;height:8px;border-radius:50%;flex:none}
.meter{position:relative;height:26px;background:var(--grid);border-radius:8px;
overflow:hidden;margin:6px 0 4px}
.meter-proj,.meter-actual{position:absolute;top:0;bottom:0;left:0;border-radius:8px 0 0 8px}
.meter-actual{opacity:.6}
.meter-budget{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink)}
.mlabel{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-bottom:14px}
.minis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.mini{background:var(--plane);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.mini .k{font-size:10.5px;color:var(--muted);text-transform:uppercase;
letter-spacing:.04em;font-weight:600}
.mini .v{font-size:16px;font-weight:640;margin-top:3px;font-variant-numeric:tabular-nums}
.rec-status{font-size:11px;color:var(--ink2);font-weight:600}
.rec-actions{white-space:nowrap}
.rec-btn{font-size:11px;font-weight:600;padding:4px 10px;border-radius:7px;
border:1px solid var(--border);background:var(--plane);color:var(--ink);cursor:pointer;
margin-left:6px}
.rec-btn.ok:hover{border-color:var(--good);color:var(--good)}
.rec-btn.no:hover{border-color:var(--crit);color:var(--crit)}
.rec-btn:disabled{opacity:.5;cursor:default}
"""


# Approve/dismiss buttons POST to /decide (served by mcca-web). Inert in a static file.
_RECS_JS = """
<script>
(function(){
  var panel=document.getElementById('recs'); if(!panel) return;
  var start=panel.dataset.start, end=panel.dataset.end;
  panel.addEventListener('click', async function(e){
    var btn=e.target.closest('.rec-btn'); if(!btn) return;
    var row=btn.closest('tr'), cell=row.querySelector('.rec-status');
    btn.disabled=true;
    try{
      var r=await fetch('/decide',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({key:row.dataset.key,status:btn.dataset.status,start:start,end:end})});
      var j=await r.json();
      if(j.status){ cell.textContent=j.status; row.style.opacity=.55; }
      else { cell.textContent='(error)'; }
    }catch(err){ cell.textContent='(offline)'; }
    btn.disabled=false;
  });
})();
</script>
"""


def render_html(data: dict[str, Any]) -> str:
    """Render the dashboard HTML from a data dict (pure function)."""
    fc = data["forecast"]
    pct = int(fc["interval"] * 100)
    services = data["services"]
    providers = data.get("providers", [])
    teams = data.get("teams", [])
    provider_label = " + ".join(p["name"] for p in providers) or "AWS"

    # Hero chart: daily area+band when we have the daily series, else the monthly fallback.
    if data.get("daily") and fc.get("points"):
        chart = _svg_forecast_area(data["daily"], fc["points"], fc["interval"])
    else:
        chart = _svg_trend(data["months"], fc)

    # KPI tiles.
    tiles = [
        ("Total billed", _money(data["total_billed"]), f"{data['start']} → {data['end']}", "s1"),
        (
            "Effective (amortized)",
            _money(data["total_effective"]),
            "after RI/SP amortization",
            "s2",
        ),
        ("Commitment savings", _money(data["savings"]), "billed − effective", "s4"),
        (
            f"Forecast next {fc['horizon']}d",
            _money(fc["mid"]),
            f"{pct}% range {_money(fc['lo'])}–{_money(fc['hi'])}",
            "s3",
        ),
    ]
    kpi_html = "".join(
        f'<div class="tile" style="border-left-color:var(--{c})">'
        f'<div class="k">{escape(k)}</div><div class="v">{escape(v)}</div>'
        f'<div class="n">{escape(n)}</div></div>'
        for k, v, n, c in tiles
    )

    provider_panel = (
        '<div class="card"><div class="card-h"><h2>Spend by cloud provider</h2></div>'
        f"{_cat_bars(providers)}</div>"
        if providers
        else ""
    )
    team_panel = (
        '<div class="card"><div class="card-h"><h2>Spend by team (attribution)</h2></div>'
        f"{_cat_bars(teams)}"
        "<div class='foot'>Untagged spend shows honestly as 'unattributed'.</div></div>"
        if teams
        else ""
    )
    grid2 = (
        f'<section class="grid2">{provider_panel}{team_panel}</section>'
        if (provider_panel or team_panel)
        else ""
    )

    budget = data.get("budget")
    if budget:
        scolor = {
            "OVER": "var(--crit)",
            "AT_RISK": "var(--serious)",
            "ON_TRACK": "var(--good)",
        }.get(budget["status"], "var(--good)")
        label = {"OVER": "Over budget", "AT_RISK": "At risk", "ON_TRACK": "On track"}.get(
            budget["status"], budget["status"]
        )
        scale = (max(budget["projected"], budget["budget"]) or 1.0) * 1.08
        proj_x = min(100.0, budget["projected"] / scale * 100)
        act_x = min(100.0, budget["actual"] / scale * 100)
        bud_x = min(100.0, budget["budget"] / scale * 100)
        minis = [
            ("Monthly budget", _money(budget["budget"])),
            ("Actual so far", _money(budget["actual"])),
            ("Projected month-end", _money(budget["projected"])),
            ("Variance", f"{_money(budget['variance'])} ({budget['variance_pct']:+.1f}%)"),
        ]
        mini_html = "".join(
            f'<div class="mini"><div class="k">{escape(k)}</div>'
            f'<div class="v">{escape(v)}</div></div>'
            for k, v in minis
        )
        budget_panel = (
            f'<div class="card"><div class="card-h"><h2>Budget — {escape(budget["month"])}</h2>'
            f'<span class="badge"><span class="dot" style="background:{scolor}"></span>'
            f"{escape(label)}</span></div>"
            f'<div class="meter">'
            f'<span class="meter-proj" style="width:{proj_x:.1f}%;background:{scolor}"></span>'
            f'<span class="meter-actual" style="width:{act_x:.1f}%;background:{scolor}"></span>'
            f'<span class="meter-budget" style="left:{bud_x:.1f}%"></span></div>'
            f'<div class="mlabel"><span>projected {_money(budget["projected"])}</span>'
            f"<span>budget line {_money(budget['budget'])}</span></div>"
            f'<div class="minis">{mini_html}</div></div>'
        )
    else:
        budget_panel = ""

    findings = data.get("findings", [])
    if findings:
        sev_color = {"HIGH": "var(--crit)", "MEDIUM": "var(--serious)", "LOW": "var(--good)"}
        finding_rows = "".join(
            f'<tr><td><span class="badge"><span class="dot" '
            f'style="background:{sev_color.get(f["severity"], "var(--good)")}"></span>'
            f"{escape(f['severity'])}</span></td>"
            f"<td>{escape(f['summary'])}<div class='foot' style='margin:3px 0 0'>&rarr; "
            f"{escape(f['recommendation'])}</div></td>"
            f"<td>{escape(f['owner'])}<br><span class='foot'>{escape(f['team'])}</span></td></tr>"
            for f in findings
        )
        findings_panel = (
            f'<div class="card"><div class="card-h">'
            f"<h2>Recommended actions ({len(findings)})</h2></div>"
            "<table><thead><tr><th>Severity</th><th>Finding &amp; recommendation</th>"
            f"<th>Owner</th></tr></thead><tbody>{finding_rows}</tbody></table>"
            "<div class='foot'>Recommend-only — a human approves; nothing is executed.</div></div>"
        )
    else:
        findings_panel = ""

    recs = data.get("recommendations", [])
    if recs:
        sev_color = {"HIGH": "var(--crit)", "MEDIUM": "var(--serious)", "LOW": "var(--good)"}
        status_counts: dict[str, int] = {}
        for r in recs:
            status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
        counts_str = " · ".join(f"{k}:{v}" for k, v in sorted(status_counts.items()))
        rec_rows = "".join(
            f'<tr data-key="{escape(r["key"])}">'
            f'<td><span class="badge"><span class="dot" '
            f'style="background:{sev_color.get(r["severity"], "var(--good)")}"></span>'
            f"{escape(r['severity'])}</span></td>"
            f"<td>{escape(r['summary'])}<div class='foot' style='margin:3px 0 0'>&rarr; "
            f"{escape(r['action'])}</div></td>"
            f'<td class="rec-status">{escape(r["status"])}</td>'
            f'<td class="rec-actions"><button class="rec-btn ok" data-status="APPROVED">'
            f'Approve</button><button class="rec-btn no" data-status="DISMISSED">Dismiss</button>'
            "</td></tr>"
            for r in recs
        )
        rec_panel = (
            f'<div class="card" id="recs" data-start="{escape(data["start"])}" '
            f'data-end="{escape(data["end"])}"><div class="card-h">'
            f"<h2>Recommendations &amp; approvals ({len(recs)})</h2>"
            f'<span class="tag">{escape(counts_str)}</span></div>'
            "<table><thead><tr><th>Severity</th><th>Recommendation</th><th>Status</th>"
            f"<th>Decision</th></tr></thead><tbody>{rec_rows}</tbody></table>"
            "<div class='foot'>A decision records intent only — nothing is executed. "
            "(Buttons work when served by <code>mcca-web</code>.)</div></div>" + _RECS_JS
        )
    else:
        rec_panel = ""

    policy = data.get("policy", [])
    if policy:
        sev_color = {"HIGH": "var(--crit)", "MEDIUM": "var(--serious)", "LOW": "var(--good)"}
        policy_rows = "".join(
            f'<tr><td><span class="badge"><span class="dot" '
            f'style="background:{sev_color.get(v["severity"], "var(--good)")}"></span>'
            f"{escape(v['severity'])}</span></td>"
            f"<td>{escape(v['summary'])}<div class='foot' style='margin:3px 0 0'>&rarr; "
            f"{escape(v['recommendation'])}</div></td></tr>"
            for v in policy
        )
        n = len(policy)
        policy_panel = (
            f'<div class="card"><div class="card-h">'
            f"<h2>Policy compliance ({n} violation{'s' if n != 1 else ''})</h2></div>"
            "<table><thead><tr><th>Severity</th><th>Violation &amp; recommendation</th></tr>"
            f"</thead><tbody>{policy_rows}</tbody></table>"
            "<div class='foot'>Governance flags policy breaches — recommend-only; "
            "a human acts, nothing is enforced.</div></div>"
        )
    else:
        policy_panel = ""

    anomalies = data.get("anomalies", {"spikes": [], "steady": []})
    spike_rows = (
        "".join(
            f"<tr><td>{escape(s['date'])}</td><td>{escape(s['service'])}</td>"
            f"<td>{_money(s['amount'])}</td><td>{s['ratio']:.1f}×</td></tr>"
            for s in anomalies["spikes"]
        )
        or "<tr><td colspan='4'>No spikes detected.</td></tr>"
    )
    steady_rows = (
        "".join(
            f"<tr><td>{escape(c['service'])}</td><td>{_money(c['monthly_estimate'])}/mo</td></tr>"
            for c in anomalies["steady"]
        )
        or "<tr><td colspan='2'>None flagged.</td></tr>"
    )
    anomaly_panel = (
        '<div class="card"><div class="card-h"><h2>Detected anomalies</h2></div>'
        "<table><thead><tr><th>Spike date</th><th>Service</th><th>Cost</th>"
        f"<th>vs baseline</th></tr></thead><tbody>{spike_rows}</tbody></table>"
        "<div class='foot' style='margin:14px 0 6px'>Steady structural spend "
        "(flat &amp; persistent — review for waste):</div>"
        "<table><thead><tr><th>Service</th><th>Est. monthly</th></tr></thead>"
        f"<tbody>{steady_rows}</tbody></table></div>"
    )

    drv = data.get("drivers")
    if drv and drv["items"]:
        driver_rows = "".join(
            f"<tr><td>{escape(d['service'])}</td><td>{_money(d['current'])}</td>"
            f"<td class='{'up' if d['delta'] > 0 else 'down'}'>"
            f"{'+' if d['delta'] >= 0 else '−'}${abs(d['delta']):,.2f}</td></tr>"
            for d in drv["items"]
        )
        sign = "+" if drv["total_delta"] >= 0 else "−"
        drivers_panel = (
            f'<div class="card"><div class="card-h"><h2>What changed — {escape(drv["period"])} '
            f"({sign}${abs(drv['total_delta']):,.2f} vs prior month)</h2></div>"
            "<table><thead><tr><th>Service</th><th>This month</th><th>Δ vs prior</th></tr>"
            f"</thead><tbody>{driver_rows}</tbody></table></div>"
        )
    else:
        drivers_panel = ""

    mom_rows = []
    for m in data["months"]:
        if m["delta_pct"] is None:
            delta = "—"
        else:
            cls = "up" if m["delta_pct"] > 0 else "down"
            delta = f'<span class="{cls}">{m["delta_pct"]:+.1f}%</span>'
        mom_rows.append(
            f"<tr><td>{escape(m['label'])}</td><td>{_money(m['amount'])}</td><td>{delta}</td></tr>"
        )
    mom_panel = (
        '<div class="card"><div class="card-h"><h2>Month over month</h2></div>'
        "<table><thead><tr><th>Month</th><th>Billed</th><th>Δ vs prior</th></tr></thead>"
        f"<tbody>{''.join(mom_rows)}</tbody></table></div>"
    )

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Cloud Cost Dashboard</title><style>{_CSS}</style></head><body><div class='wrap'>"
        "<header class='hd'><div><h1>Multi-Cloud Cost Dashboard</h1>"
        f"<div class='sub'>{escape(provider_label)} &middot; {escape(data['start'])} to "
        f"{escape(data['end'])} &middot; generated {escape(data['generated'])}</div></div>"
        "<div class='live'>&#9679; grounded &middot; every figure from a query</div></header>"
        f"<section class='kpis'>{kpi_html}</section>"
        "<div class='card'><div class='card-h'>"
        f"<h2>Daily spend &amp; {fc['horizon']}-day forecast</h2>"
        f"<span class='tag'>{pct}% interval</span></div><div class='chart'>{chart}</div>"
        f"<div class='foot'>Model {escape(fc['model'])} &middot; shaded band = {pct}% "
        "prediction interval &middot; from the daily_spend query + forecaster</div></div>"
        f"{budget_panel}"
        f"{grid2}"
        "<div class='card'><div class='card-h'><h2>Top services by usage cost</h2></div>"
        f"{_mag_bars(services)}</div>"
        f"{rec_panel}"
        f"{findings_panel}"
        f"{policy_panel}"
        f"{drivers_panel}"
        f"{anomaly_panel}"
        f"{mom_panel}"
        "<div class='foot'>Every figure is produced by a validated query, the forecaster, or "
        "a deterministic detector — never by a language model.</div>"
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
