"""Integration: insert -> read through PostgresRepository against a live Postgres.

Requires `docker compose up -d`. Skips automatically if the DB is unreachable so the
unit suite always runs. Confirms an untagged record lands as 'unattributed' on all four
attribution columns.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.models import FocusRecord
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import UNATTRIBUTED, metadata

pytestmark = pytest.mark.integration


@pytest.fixture
def repo():
    # Short connect timeout so the suite skips fast when Postgres is down,
    # instead of blocking on a long TCP timeout.
    engine = create_warehouse_engine(connect_args={"connect_timeout": 3})
    try:
        conn = engine.connect()
    except OperationalError:
        pytest.skip("Postgres not reachable — run `docker compose up -d`.")
    conn.close()
    # Clean slate for the test table.
    metadata.drop_all(engine)
    metadata.create_all(engine)
    yield PostgresRepository(engine=engine)
    metadata.drop_all(engine)
    engine.dispose()


def test_insert_and_read_back(repo: PostgresRepository, sample_record: FocusRecord) -> None:
    written = repo.insert_records([sample_record])
    assert written == 1

    rows = repo.fetch_all()
    assert len(rows) == 1
    row = rows[0]

    assert str(row["billed_cost"]) == "12.3400000000"
    # Untagged spend is attributed honestly, not dropped.
    assert row["x_team"] == UNATTRIBUTED
    assert row["x_service"] == UNATTRIBUTED
    assert row["x_environment"] == UNATTRIBUTED
    assert row["x_owner"] == UNATTRIBUTED


def test_execute_runs_registered_query(
    repo: PostgresRepository, sample_record: FocusRecord
) -> None:
    # The only figure path is a registered, validated query executed via repo.execute.
    from datetime import date

    from mcca.queries.registry import run_query

    repo.insert_records([sample_record])
    result = run_query(repo, "total_spend", {"start": date(2026, 6, 1), "end": date(2026, 6, 2)})
    assert result.name == "total_spend"
    assert result.rows[0]["billed_cost"] == sample_record.billed_cost
