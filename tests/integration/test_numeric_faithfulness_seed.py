"""Integration: every fixed query returns the fixture-exact figure (numeric faithfulness).

Seeds all three clouds from the deterministic generator, then asserts each agent-facing
query's numbers equal an INDEPENDENT Python aggregation of the same rows (see
mcca.eval.numeric). This is the strongest correctness guarantee available on synthetic
data. It does NOT claim reconciliation to a real console — that remains an open debt.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from mcca.eval.numeric import run_numeric_checks
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import (
    seed_azure_warehouse,
    seed_gcp_warehouse,
    seed_warehouse,
)
from mcca.queries.registry import run_query
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import metadata

pytestmark = pytest.mark.integration

START = date(2026, 1, 1)
END = date(2026, 3, 1)  # two full months


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
    cfg = GeneratorConfig(seed=42)
    seed_warehouse(repository, START, END, config=cfg)
    seed_azure_warehouse(repository, START, END, config=cfg)
    seed_gcp_warehouse(repository, START, END, config=cfg)
    yield repository
    metadata.drop_all(engine)
    engine.dispose()


def test_fixture_is_non_empty(repo: PostgresRepository) -> None:
    # Guard against a vacuous pass: there must actually be spend to check.
    total = run_query(repo, "total_spend", {"start": START, "end": END}).rows[0]
    assert Decimal(str(total["billed_cost"])) > 0


def test_every_fixed_query_returns_fixture_exact_figures(repo: PostgresRepository) -> None:
    results = run_numeric_checks(repo, START, END)
    failures = [r for r in results if not r.passed]
    # Every registered agent-facing query is covered and must match ground truth exactly.
    covered = {r.name for r in results}
    assert covered == {
        "total_spend",
        "spend_by_service",
        "spend_by_provider",
        "spend_by_charge_category",
        "spend_by_team",
        "spend_by_environment",
        "daily_spend",
        "monthly_spend",
        "month_over_month",
    }
    assert not failures, "numeric mismatches: " + " | ".join(
        f"{r.name}: {r.note}" for r in failures
    )


def test_effective_cost_also_reconciles(repo: PostgresRepository) -> None:
    # Re-run against the amortized measure to prove both cost columns are faithful.
    results = run_numeric_checks(repo, START, END, metric="effective_cost")
    assert all(r.passed for r in results)
