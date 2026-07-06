"""Seed the warehouse with synthetic AWS cost history (demo, no AWS account needed).

Run:  uv run mcca-seed            # ~9 months of daily data into the local Postgres
      uv run mcca-seed --months 12 --keep

By default this RESETS the focus_costs table first (it is a demo warehouse). Pass
--keep to append instead. Data flows through the real normalize -> repository path.
"""

from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import delete, func, select

from mcca.config import get_settings
from mcca.ingestion.aws.loader import ingest_cost_and_usage
from mcca.ingestion.synthetic.client import SyntheticCostExplorerClient
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.logging import configure_logging
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.repository import WarehouseRepository
from mcca.warehouse.schema import focus_costs


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _minus_months(d: date, months: int) -> date:
    """First day of the month `months` before the month containing d."""
    total = (d.year * 12 + (d.month - 1)) - months
    return date(total // 12, total % 12 + 1, 1)


def seed_warehouse(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    config: GeneratorConfig | None = None,
) -> int:
    """Generate [start, end) of synthetic cost data and load it via the repository."""
    client = SyntheticCostExplorerClient(config)
    return ingest_cost_and_usage(repo, start, end, client=client)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the warehouse with synthetic AWS costs.")
    parser.add_argument("--months", type=int, default=9, help="Months of history (default 9).")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility.")
    parser.add_argument("--keep", action="store_true", help="Append instead of resetting.")
    args = parser.parse_args()

    configure_logging()
    get_settings()  # validate config / load .env early

    repo = PostgresRepository()
    repo.create_schema()

    end = _first_of_month(date.today())  # exclusive: up to the start of this month
    start = _minus_months(end, args.months)

    if not args.keep:
        print("Resetting focus_costs (demo warehouse) before seeding...")
        with repo.engine.begin() as conn:
            conn.execute(delete(focus_costs))

    written = seed_warehouse(repo, start, end, config=GeneratorConfig(seed=args.seed))

    with repo.engine.connect() as conn:
        total_billed = conn.execute(select(func.sum(focus_costs.c.billed_cost))).scalar_one()
        total_effective = conn.execute(select(func.sum(focus_costs.c.effective_cost))).scalar_one()

    print(f"Seeded {written} rows from {start} to {end} (exclusive).")
    print(f"Total billed (NetUnblended):   ${total_billed:,.2f}")
    print(f"Total effective (NetAmortized): ${total_effective:,.2f}")


if __name__ == "__main__":
    main()
