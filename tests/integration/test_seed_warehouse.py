"""Integration: seed synthetic data into Postgres and verify it lands correctly.

Requires `docker compose up -d`; skips automatically if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import focus_costs, metadata

pytestmark = pytest.mark.integration


@pytest.fixture
def repo():
    engine = create_warehouse_engine(connect_args={"connect_timeout": 3})
    try:
        engine.connect().close()
    except OperationalError:
        pytest.skip("Postgres not reachable — run `docker compose up -d`.")
    metadata.drop_all(engine)
    metadata.create_all(engine)
    yield PostgresRepository(engine=engine)
    metadata.drop_all(engine)
    engine.dispose()


def test_seed_one_month(repo: PostgresRepository) -> None:
    written = seed_warehouse(
        repo, date(2026, 3, 1), date(2026, 4, 1), config=GeneratorConfig(seed=42)
    )
    assert written > 200  # ~8 services x 31 days + tax/fee/credit lines

    with repo.engine.connect() as conn:
        rows = conn.execute(select(func.count()).select_from(focus_costs)).scalar_one()
        total_billed = conn.execute(select(func.sum(focus_costs.c.billed_cost))).scalar_one()
        services = conn.execute(
            select(func.count(func.distinct(focus_costs.c.service_name)))
        ).scalar_one()

    assert rows == written
    assert total_billed > Decimal("1000")  # a month of realistic spend
    assert services >= 8
