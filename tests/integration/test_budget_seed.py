"""Integration: budget store + spend_vs_budget against seeded Postgres.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from mcca.budgets.service import spend_vs_budget
from mcca.budgets.store import get_budget, upsert_budget
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import metadata

pytestmark = pytest.mark.integration

START = date(2026, 1, 1)
END = date(2026, 6, 1)  # data through 2026-05-31


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
    upsert_budget(repository, Decimal("9000"))
    yield repository
    metadata.drop_all(engine)
    engine.dispose()


def test_no_budget_returns_none() -> None:
    engine = create_warehouse_engine(connect_args={"connect_timeout": 3})
    try:
        engine.connect().close()
    except OperationalError:
        pytest.skip("Postgres not reachable.")
    metadata.drop_all(engine)
    metadata.create_all(engine)
    repo = PostgresRepository(engine=engine)
    try:
        assert spend_vs_budget(repo, date(2026, 6, 1)) is None  # no budget set
    finally:
        metadata.drop_all(engine)
        engine.dispose()


def test_budget_upsert_is_idempotent(repo: PostgresRepository) -> None:
    upsert_budget(repo, Decimal("12345"))
    row = get_budget(repo)
    assert Decimal(str(row["monthly_amount"])) == Decimal("12345")
    upsert_budget(repo, Decimal("9000"))  # restore for other tests


def test_future_month_is_all_forecast(repo: PostgresRepository) -> None:
    # June 2026 has no actuals (data ends 2026-05-31) -> projection is pure forecast.
    status = spend_vs_budget(repo, date(2026, 6, 1))
    assert status is not None
    assert status.actual == Decimal("0")
    assert status.projected == status.forecast_mid
    assert status.projected > Decimal("0")
    assert status.status in {"ON_TRACK", "AT_RISK", "OVER"}
    assert status.projected_lo <= status.projected <= status.projected_hi


def test_past_month_is_all_actual(repo: PostgresRepository) -> None:
    # April 2026 is fully in the data -> no forecast component.
    status = spend_vs_budget(repo, date(2026, 4, 15))
    assert status is not None
    assert status.forecast_mid == Decimal("0")
    assert status.actual > Decimal("0")
    assert status.projected == status.actual
