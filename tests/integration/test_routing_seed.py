"""Integration: routing produces owner-attributed findings against seeded data.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from mcca.budgets.store import upsert_budget
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.routing.router import route
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import metadata

pytestmark = pytest.mark.integration

START = date(2026, 1, 1)
END = date(2026, 7, 1)


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


def test_findings_are_routed_to_owners(repo: PostgresRepository) -> None:
    report = route(repo, START, END, budget_month=date(2026, 7, 1))
    kinds = {f.kind for f in report.findings}
    assert {"SPIKE", "WASTE", "BUDGET"} <= kinds

    # Tagged services route to a named owner; the untagged EBS waste is unassigned.
    ec2 = next((f for f in report.findings if f.service and "Elastic Compute" in f.service), None)
    assert ec2 is not None
    assert ec2.owner != "unassigned"

    ebs = next((f for f in report.findings if f.service == "Amazon Elastic Block Store"), None)
    assert ebs is not None
    assert ebs.owner == "unattributed"  # untagged waste routes to unattributed, honestly
    assert ebs.team == "unattributed"

    # Every finding carries a recommendation and is HIGH/MEDIUM/LOW.
    assert all(f.recommendation for f in report.findings)
    assert all(f.severity in {"HIGH", "MEDIUM", "LOW"} for f in report.findings)
