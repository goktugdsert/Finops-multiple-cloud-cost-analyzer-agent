"""Integration: forecast against real seeded history in Postgres.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from mcca.forecasting.service import forecast_daily_spend
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import metadata

pytestmark = pytest.mark.integration

START = date(2026, 1, 1)
END = date(2026, 6, 1)  # five months of daily history


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


def test_forecast_from_seeded_history(repo: PostgresRepository) -> None:
    fc = forecast_daily_spend(repo, START, END, horizon=30, interval=0.8)

    assert fc.model.startswith("SARIMAX")  # months of daily data -> full model
    assert len(fc.points) == 30
    assert fc.history_points >= 140
    assert fc.history_start == START
    assert fc.history_end == END - timedelta(days=1)

    for p in fc.points:
        assert p.lower <= p.yhat <= p.upper
        assert p.yhat > Decimal("0")
    # An 80% band should have real width (not a degenerate point forecast).
    assert fc.points[-1].upper > fc.points[-1].lower
