"""Live-feed simulator: advance the clock one day per tick and ingest, near-real-time.

    uv run mcca-simulate                 # ~21 days, 3s/day, into local Postgres
    uv run mcca-simulate --days 30 --interval 1 --no-monitor

Each tick moves the simulated "today" forward one day and re-ingests the whole window so far
through the REAL loaders (idempotent upsert — re-ingesting earlier days corrects, never
double-counts). The newest AWS day is a partial-day ESTIMATE; the next tick restates it to
its final value, exercising estimate->final reconciliation live. After each tick a monitor
runs the detection / governance / budget modules and prints any NEW findings.

This is a demo/data tool only — it drives the existing synthetic ingest + read paths and
never touches the trust boundary (numbers still come from deterministic queries).
"""

from __future__ import annotations

import argparse
import time
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from mcca.budgets.service import spend_vs_budget
from mcca.budgets.store import upsert_budget
from mcca.config import get_settings
from mcca.detection.service import detect
from mcca.governance.service import evaluate_policies
from mcca.governance.store import seed_default_policies
from mcca.ingestion.aws.loader import ingest_cost_and_usage
from mcca.ingestion.synthetic.client import SyntheticCostExplorerClient
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_azure_warehouse, seed_gcp_warehouse
from mcca.logging import configure_logging
from mcca.queries.registry import run_query
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.repository import WarehouseRepository
from mcca.warehouse.schema import focus_costs


def ingest_day(
    repo: WarehouseRepository,
    origin: date,
    today: date,
    config: GeneratorConfig,
    estimate_factor: float,
) -> None:
    """Ingest [origin, today] (idempotent) with the newest AWS day as a partial estimate."""
    end = today + timedelta(days=1)
    aws_cfg = replace(config, estimate_from=today, estimate_factor=estimate_factor)
    ingest_cost_and_usage(repo, origin, end, client=SyntheticCostExplorerClient(aws_cfg))
    seed_azure_warehouse(repo, origin, end, config=config)
    seed_gcp_warehouse(repo, origin, end, config=config)


def scan(repo: WarehouseRepository, origin: date, today: date) -> list[str]:
    """Current findings across detection + governance + budget (each figure is grounded).

    Each check is independent and best-effort — e.g. the budget forecast needs a few days of
    history, so it silently skips on the first tick rather than noising up the feed.
    """
    end = today + timedelta(days=1)
    items: list[str] = []
    try:
        det = detect(repo, origin, end)
        items += [
            f"SPIKE   {s.service} {s.ratio:.1f}x on {s.date} (${s.amount})" for s in det.spikes
        ]
    except Exception:  # noqa: BLE001 - a monitor hiccup must not stop the feed
        pass
    try:
        for v in evaluate_policies(repo, origin, end):
            items.append(f"POLICY  [{v.severity}] {v.summary}")
    except Exception:  # noqa: BLE001
        pass
    try:
        bs = spend_vs_budget(repo, today)
        if bs is not None and bs.status in ("OVER", "AT_RISK"):
            items.append(f"BUDGET  {bs.status} {bs.month:%b %Y} projected ${bs.projected:,.0f}")
    except Exception:  # noqa: BLE001 - too little history to forecast yet -> skip silently
        pass
    return items


def _total(repo: WarehouseRepository, origin: date, today: date) -> float:
    rows = run_query(repo, "total_spend", {"start": origin, "end": today + timedelta(days=1)}).rows
    return float(rows[0]["billed_cost"])


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _minus_months(d: date, months: int) -> date:
    total = (d.year * 12 + (d.month - 1)) - months
    return date(total // 12, total % 12 + 1, 1)


def run(
    repo: WarehouseRepository,
    origin: date,
    days: int,
    *,
    interval: float,
    estimate_factor: float,
    seed: int,
    monitor: bool,
    sleep=time.sleep,
) -> None:
    """Run the simulation loop for `days` ticks starting at `origin`."""
    config = GeneratorConfig(seed=seed)
    seen: set[str] = set()
    print(f"Simulating {days} days from {origin} at {interval}s/day (Ctrl+C to stop)\n")
    for t in range(days):
        today = origin + timedelta(days=t)
        ingest_day(repo, origin, today, config, estimate_factor)
        total = _total(repo, origin, today)
        print(
            f"[day {t + 1:>2}/{days}] {today}  total=${total:,.0f}  "
            f"(AWS {today} is an estimate ×{estimate_factor}, restated next tick)"
        )
        if monitor:
            for item in scan(repo, origin, today):
                if item not in seen:
                    seen.add(item)
                    print(f"    NEW  {item}")
        if t < days - 1:
            sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live near-real-time cost-data simulator.")
    parser.add_argument("--days", type=int, default=21, help="Simulated days to run (default 21).")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds per day (default 3).")
    parser.add_argument("--origin", default=None, help="Start date YYYY-MM-DD (default: 9mo ago).")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default 42).")
    parser.add_argument(
        "--estimate-factor", type=float, default=0.85, help="Newest-day estimate scale."
    )
    parser.add_argument("--budget", type=float, default=9000.0, help="Monthly total budget.")
    parser.add_argument("--keep", action="store_true", help="Don't clear existing cost data.")
    parser.add_argument("--no-monitor", action="store_true", help="Skip the findings monitor.")
    args = parser.parse_args()

    configure_logging()
    get_settings()
    repo = PostgresRepository()
    repo.create_schema()

    origin = (
        date.fromisoformat(args.origin)
        if args.origin
        else _minus_months(_first_of_month(date.today()), 9)
    )
    if not args.keep:
        with repo.engine.begin() as conn:
            conn.execute(focus_costs.delete())
        print("Cleared focus_costs — starting from an empty warehouse.")
    upsert_budget(repo, Decimal(str(args.budget)))
    seed_default_policies(repo)

    try:
        run(
            repo,
            origin,
            args.days,
            interval=args.interval,
            estimate_factor=args.estimate_factor,
            seed=args.seed,
            monitor=not args.no_monitor,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    print("\nWatch it live: uv run mcca-web, open http://127.0.0.1:8000/?refresh=5")


if __name__ == "__main__":
    main()
