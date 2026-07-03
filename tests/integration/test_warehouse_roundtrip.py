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


def test_named_query_path_is_locked(repo: PostgresRepository) -> None:
    # No ad-hoc SQL path exists yet: the only figure path is the (not-yet-built)
    # validated query registry.
    with pytest.raises(NotImplementedError):
        repo.run_named_query("spend_by_service")
