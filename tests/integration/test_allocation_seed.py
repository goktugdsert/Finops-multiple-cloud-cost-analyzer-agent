"""Integration: allocating shared spend yields fully-loaded team cost that reconciles.

Proven against seeded data: the sum of every team's fully-loaded total (direct + allocated)
plus any unallocated remainder equals the true grand total from total_spend — allocation
redistributes, it never creates or loses money.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from mcca.allocation.service import allocate_team_spend
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


def test_allocation_conserves_and_matches_grand_total(repo: PostgresRepository) -> None:
    grand_total = Decimal(
        str(run_query(repo, "total_spend", {"start": START, "end": END}).rows[0]["billed_cost"])
    )
    res = allocate_team_spend(repo, START, END)

    # There is a real shared pool to allocate (AWS seed has untagged waste + tax + fees).
    assert res.shared_pool != 0
    assert res.unallocated == Decimal("0.00")  # attributed teams exist -> fully allocated

    direct = sum((t.direct for t in res.teams), Decimal("0"))
    loaded = sum((t.total for t in res.teams), Decimal("0"))
    # Allocation conserves EXACTLY what it was given (cent-precise redistribution).
    assert direct + res.shared_pool == loaded + res.unallocated
    # And that fully-loaded total matches the true grand total (within per-team cent rounding).
    assert abs(loaded - grand_total) < Decimal("0.05")


def test_proportional_beats_direct_for_the_biggest_team(repo: PostgresRepository) -> None:
    res = allocate_team_spend(repo, START, END, method="proportional")
    # Every attributed team's fully-loaded total is >= its direct spend (it gains a share).
    assert all(t.total >= t.direct for t in res.teams)
    # The pool actually moved onto teams.
    assert any(t.allocated > 0 for t in res.teams)
