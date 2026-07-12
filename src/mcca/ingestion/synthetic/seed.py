"""Seed the warehouse with synthetic AWS cost history (demo, no AWS account needed).

Run:  uv run mcca-seed            # ~9 months of daily data into the local Postgres
      uv run mcca-seed --months 12 --keep

By default this RESETS the focus_costs table first (it is a demo warehouse). Pass
--keep to append instead. Data flows through the real normalize -> repository path.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select

from mcca.budgets.store import upsert_budget
from mcca.config import get_settings
from mcca.governance.store import seed_default_policies
from mcca.ingestion.aws.loader import ingest_cost_and_usage
from mcca.ingestion.azure.loader import ingest_cost_management
from mcca.ingestion.gcp.loader import ingest_billing_export
from mcca.ingestion.synthetic.azure import SyntheticAzureClient
from mcca.ingestion.synthetic.client import SyntheticCostExplorerClient
from mcca.ingestion.synthetic.gcp import SyntheticBigQueryClient
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
    """Generate [start, end) of synthetic AWS cost data and load it via the repository."""
    client = SyntheticCostExplorerClient(config)
    return ingest_cost_and_usage(repo, start, end, client=client)


def seed_azure_warehouse(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    config: GeneratorConfig | None = None,
) -> int:
    """Generate [start, end) of synthetic Azure cost data and load it via the repository."""
    client = SyntheticAzureClient(config)
    return ingest_cost_management(repo, start, end, client=client)


def seed_gcp_warehouse(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    config: GeneratorConfig | None = None,
) -> int:
    """Generate [start, end) of synthetic GCP cost data and load it via the repository."""
    client = SyntheticBigQueryClient(config)
    return ingest_billing_export(repo, start, end, client=client)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the warehouse with synthetic AWS costs.")
    parser.add_argument("--months", type=int, default=9, help="Months of history (default 9).")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility.")
    parser.add_argument("--keep", action="store_true", help="Append instead of resetting.")
    parser.add_argument(
        "--cloud",
        choices=["aws", "azure", "gcp", "all"],
        default="all",
        help="Which cloud(s) to seed (default all).",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=9000.0,
        help="Monthly total budget to set for tracking (default 9000).",
    )
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

    cfg = GeneratorConfig(seed=args.seed)
    written = 0
    if args.cloud in ("aws", "all"):
        n = seed_warehouse(repo, start, end, config=cfg)
        written += n
        print(f"Seeded {n} AWS rows.")
    if args.cloud in ("azure", "all"):
        n = seed_azure_warehouse(repo, start, end, config=cfg)
        written += n
        print(f"Seeded {n} Azure rows.")
    if args.cloud in ("gcp", "all"):
        n = seed_gcp_warehouse(repo, start, end, config=cfg)
        written += n
        print(f"Seeded {n} GCP rows.")
    upsert_budget(repo, Decimal(str(args.budget)))
    seed_default_policies(repo)  # populate the governance policy table with sensible defaults

    with repo.engine.connect() as conn:
        total_billed = conn.execute(select(func.sum(focus_costs.c.billed_cost))).scalar_one()
        by_provider = conn.execute(
            select(focus_costs.c.provider_name, func.sum(focus_costs.c.billed_cost))
            .group_by(focus_costs.c.provider_name)
            .order_by(func.sum(focus_costs.c.billed_cost).desc())
        ).all()

    print(f"\nSeeded {written} rows total from {start} to {end} (exclusive).")
    for provider, billed in by_provider:
        print(f"  {provider:<8} ${billed:,.2f}")
    print(f"Total billed:      ${total_billed:,.2f}")
    print(f"Monthly budget:    ${args.budget:,.2f} (total)")


if __name__ == "__main__":
    main()
