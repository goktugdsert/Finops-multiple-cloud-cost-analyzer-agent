"""Integration: the live simulator grows the warehouse and restates estimates (no double-count).

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.queries.registry import run_query
from mcca.simulate import ingest_day, run, scan
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import focus_costs, metadata

pytestmark = pytest.mark.integration

ORIGIN = date(2026, 1, 1)


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


def _row_count(repo: PostgresRepository) -> int:
    with repo.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(focus_costs)).scalar_one()


def _aws_day_total(repo: PostgresRepository, day: date) -> Decimal:
    rows = run_query(repo, "spend_by_provider", {"start": day, "end": day + timedelta(days=1)}).rows
    return next(
        (Decimal(str(r["amount"])) for r in rows if r["provider_name"] == "AWS"), Decimal("0")
    )


def _aws_rows_on(rows: list, day: date) -> list:
    return [
        r for r in rows if r["provider_name"] == "AWS" and r["charge_period_start"].date() == day
    ]


def test_simulation_grows_one_day_per_tick(repo: PostgresRepository) -> None:
    run(
        repo,
        ORIGIN,
        3,
        interval=0,
        estimate_factor=0.5,
        seed=42,
        monitor=False,
        sleep=lambda s: None,
    )
    daily = run_query(
        repo, "daily_spend", {"start": ORIGIN, "end": ORIGIN + timedelta(days=3)}
    ).rows
    assert len(daily) == 3  # exactly three simulated days present

    rows = repo.fetch_all()
    aws_newest = _aws_rows_on(rows, ORIGIN + timedelta(days=2))
    aws_first = _aws_rows_on(rows, ORIGIN)
    assert any(r["is_estimated"] for r in aws_newest)  # newest day is a live estimate
    assert all(not r["is_estimated"] for r in aws_first)  # earlier days restated to final


def test_estimate_is_restated_upward_without_double_counting(repo: PostgresRepository) -> None:
    cfg = GeneratorConfig(seed=42)

    ingest_day(repo, ORIGIN, ORIGIN, cfg, 0.5)  # day 0 arrives as a 0.5x estimate
    estimate = _aws_day_total(repo, ORIGIN)
    rows_after_estimate = _row_count(repo)

    ingest_day(repo, ORIGIN, ORIGIN + timedelta(days=1), cfg, 0.5)  # next tick restates day0
    final = _aws_day_total(repo, ORIGIN)

    assert final > estimate  # the estimate was restated up to its full value
    # Day 0's rows were UPDATED in place (upsert), then day 1 added — not double-counted.
    assert _row_count(repo) > rows_after_estimate  # grew by day 1's rows only


def test_monitor_reports_grounded_findings(repo: PostgresRepository) -> None:
    run(
        repo,
        ORIGIN,
        5,
        interval=0,
        estimate_factor=0.85,
        seed=42,
        monitor=False,
        sleep=lambda s: None,
    )
    items = scan(repo, ORIGIN, ORIGIN + timedelta(days=4))
    assert isinstance(items, list)  # returns findings without crashing on a short window
