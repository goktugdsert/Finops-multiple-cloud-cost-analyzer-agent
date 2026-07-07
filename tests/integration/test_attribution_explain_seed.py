"""Integration: attribution populates from tags, and explain_change finds drivers.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from mcca.analysis.drivers import explain_change
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.queries.registry import run_query
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import metadata

pytestmark = pytest.mark.integration

START = date(2026, 1, 1)
END = date(2026, 4, 1)


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


def test_spend_attributed_to_real_teams(repo: PostgresRepository) -> None:
    rows = run_query(repo, "spend_by_team", {"start": START, "end": END}).rows
    teams = {r["x_team"]: r["amount"] for r in rows}
    # Tagged usage rolls up to platform/data; untagged (EBS, tax, credits) is honest.
    assert "platform" in teams
    assert "data" in teams
    assert "unattributed" in teams
    assert teams["platform"] > Decimal("0")


def test_environment_attribution(repo: PostgresRepository) -> None:
    rows = run_query(repo, "spend_by_environment", {"start": START, "end": END}).rows
    envs = {r["x_environment"] for r in rows}
    assert {"prod", "staging"} <= envs  # Lambda is tagged staging


def test_explain_change_ranks_service_drivers(repo: PostgresRepository) -> None:
    exp = explain_change(
        repo, date(2026, 3, 1), END, prior_start=date(2026, 2, 1), prior_end=date(2026, 3, 1)
    )
    assert exp.drivers  # some services moved
    # Drivers are sorted by absolute delta.
    magnitudes = [abs(d.delta) for d in exp.drivers]
    assert magnitudes == sorted(magnitudes, reverse=True)
    # The reported total delta equals current minus prior totals.
    assert exp.total_delta == exp.current_total - exp.prior_total
