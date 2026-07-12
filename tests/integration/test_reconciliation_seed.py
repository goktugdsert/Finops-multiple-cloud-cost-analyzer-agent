"""Integration: ingestion reconciles (upserts) instead of appending.

Two guarantees, proven against Postgres:
  1. Re-ingesting the same period does NOT double-count — totals and row counts hold.
  2. An estimate is overwritten in place by its final restatement (same billing line),
     rather than leaving two rows that sum to the wrong number.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from mcca.ingestion.aws.cost_explorer import flatten_response
from mcca.ingestion.aws.normalize import normalize_records
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.queries.registry import run_query
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import focus_costs, metadata

pytestmark = pytest.mark.integration

START = date(2026, 3, 1)
END = date(2026, 4, 1)  # one month


@pytest.fixture
def repo():
    engine = create_warehouse_engine(connect_args={"connect_timeout": 3})
    try:
        engine.connect().close()
    except OperationalError:
        pytest.skip("Postgres not reachable — run `docker compose up -d`.")
    metadata.drop_all(engine)
    metadata.create_all(engine)
    repository = PostgresRepository(engine=engine)
    yield repository
    metadata.drop_all(engine)
    engine.dispose()


def _row_count(repo: PostgresRepository) -> int:
    with repo.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(focus_costs)).scalar_one()


def _total(repo: PostgresRepository) -> Decimal:
    return Decimal(
        str(run_query(repo, "total_spend", {"start": START, "end": END}).rows[0]["billed_cost"])
    )


def test_reingesting_same_period_does_not_drift(repo: PostgresRepository) -> None:
    cfg = GeneratorConfig(seed=42)

    seed_warehouse(repo, START, END, config=cfg)
    rows_after_first = _row_count(repo)
    total_after_first = _total(repo)

    # Ingest the identical period a second and third time.
    seed_warehouse(repo, START, END, config=cfg)
    seed_warehouse(repo, START, END, config=cfg)

    # Upsert keyed on natural identity -> no new rows, no inflated totals.
    assert _row_count(repo) == rows_after_first
    assert _total(repo) == total_after_first


# A single AWS Cost Explorer daily bucket for one service. `estimated` and `amount` vary
# between the estimate and the final; every identity field is held constant so the two
# describe the SAME billing line.
def _ce_page(amount: str, *, estimated: bool) -> dict:
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-03-15", "End": "2026-03-16"},
                "Estimated": estimated,
                "Groups": [
                    {
                        "Keys": ["Amazon Elastic Compute Cloud - Compute", "Usage"],
                        "Metrics": {
                            "NetUnblendedCost": {"Amount": amount, "Unit": "USD"},
                            "NetAmortizedCost": {"Amount": amount, "Unit": "USD"},
                            "UsageQuantity": {"Amount": "100", "Unit": "Hrs"},
                        },
                    }
                ],
            }
        ]
    }


def _ingest_page(repo: PostgresRepository, page: dict) -> None:
    records = normalize_records(flatten_response([page]), billing_account_id="acct-1")
    repo.upsert_records(records)


def test_estimate_is_overwritten_by_final(repo: PostgresRepository) -> None:
    # First ingest: an ESTIMATE of $100.
    _ingest_page(repo, _ce_page("100.00", estimated=True))
    rows = repo.fetch_all()
    assert len(rows) == 1
    assert rows[0]["is_estimated"] is True
    assert Decimal(str(rows[0]["billed_cost"])) == Decimal("100.00")

    # Second ingest: the FINAL restatement of the same line to $150.
    _ingest_page(repo, _ce_page("150.00", estimated=False))
    rows = repo.fetch_all()

    # Reconciled in place: still ONE row, now the final amount, flag cleared.
    assert len(rows) == 1
    assert rows[0]["is_estimated"] is False
    assert Decimal(str(rows[0]["billed_cost"])) == Decimal("150.00")
