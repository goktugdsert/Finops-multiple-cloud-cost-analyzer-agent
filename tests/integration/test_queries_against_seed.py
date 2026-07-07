"""Integration: run the fixed queries against seeded data and check they reconcile.

This is where "numbers provably correct" gets teeth: the query results must agree with
each other (e.g. total == sum of category breakdown) and with the seeded structure.
Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.queries.registry import run_query
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import UNATTRIBUTED, metadata

pytestmark = pytest.mark.integration

START = date(2026, 3, 1)
END = date(2026, 5, 1)  # two full months


@pytest.fixture(scope="module")
def repo():
    engine = create_warehouse_engine(connect_args={"connect_timeout": 3})
    try:
        engine.connect().close()
    except OperationalError:
        pytest.skip("Postgres not reachable — run `docker compose up -d`.")
    metadata.drop_all(engine)
    metadata.create_all(engine)
    repository = PostgresRepository(engine=engine)
    seed_warehouse(repository, START, END, config=GeneratorConfig(seed=42))
    yield repository
    metadata.drop_all(engine)
    engine.dispose()


def _params() -> dict:
    return {"start": START, "end": END}


def test_total_reconciles_with_category_breakdown(repo: PostgresRepository) -> None:
    total = run_query(repo, "total_spend", _params()).rows[0]["billed_cost"]
    categories = run_query(repo, "spend_by_charge_category", _params()).rows
    assert sum(r["amount"] for r in categories) == total
    # The bill has usage, tax, a recurring purchase, and negative credits.
    cats = {r["charge_category"] for r in categories}
    assert {"Usage", "Tax", "Purchase", "Credit"} <= cats
    credit = next(r["amount"] for r in categories if r["charge_category"] == "Credit")
    assert credit < 0


def test_spend_by_service_ranks_ec2_top(repo: PostgresRepository) -> None:
    rows = run_query(repo, "spend_by_service", {**_params(), "limit": 3}).rows
    assert len(rows) == 3
    assert rows[0]["service_name"] == "Amazon Elastic Compute Cloud - Compute"
    # Ordered strictly descending by amount.
    amounts = [r["amount"] for r in rows]
    assert amounts == sorted(amounts, reverse=True)


def test_daily_series_covers_every_day(repo: PostgresRepository) -> None:
    rows = run_query(repo, "daily_spend", _params()).rows
    assert len(rows) == (END - START).days  # 61 days
    assert all(r["amount"] is not None for r in rows)


def test_monthly_and_mom(repo: PostgresRepository) -> None:
    monthly = run_query(repo, "monthly_spend", _params()).rows
    assert len(monthly) == 2

    mom = run_query(repo, "month_over_month", _params()).rows
    assert mom[0]["prev_amount"] is None  # first month has no prior
    assert mom[1]["prev_amount"] == monthly[0]["amount"]
    assert mom[1]["delta"] == monthly[1]["amount"] - monthly[0]["amount"]
    # Effective spend is lower than billed thanks to RI/SP amortization.
    billed = run_query(repo, "total_spend", _params()).rows[0]
    assert billed["effective_cost"] < billed["billed_cost"]


def test_attribution_splits_by_team_with_honest_unattributed(repo: PostgresRepository) -> None:
    teams = {r["x_team"]: r["amount"] for r in run_query(repo, "spend_by_team", _params()).rows}
    # Tagged usage rolls up to teams; untagged spend (EBS, tax, credits) stays honest.
    assert "platform" in teams
    assert "data" in teams
    assert teams[UNATTRIBUTED] > Decimal("0")
