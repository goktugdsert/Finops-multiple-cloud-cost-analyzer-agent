"""Integration: seed AWS + Azure into one warehouse; unified queries span both.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

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
    cfg = GeneratorConfig(seed=42)
    seed_warehouse(repository, START, END, config=cfg)
    seed_azure_warehouse(repository, START, END, config=cfg)
    seed_gcp_warehouse(repository, START, END, config=cfg)
    yield repository
    metadata.drop_all(engine)
    engine.dispose()


def _params():
    return {"start": START, "end": END}


def test_spend_by_provider_covers_all_clouds(repo: PostgresRepository) -> None:
    rows = run_query(repo, "spend_by_provider", _params()).rows
    providers = {r["provider_name"]: r["amount"] for r in rows}
    assert set(providers) == {"AWS", "Azure", "GCP"}
    assert all(v > Decimal("0") for v in providers.values())


def test_total_spend_sums_all_clouds(repo: PostgresRepository) -> None:
    total = run_query(repo, "total_spend", _params()).rows[0]["billed_cost"]
    by_provider = run_query(repo, "spend_by_provider", _params()).rows
    assert sum(r["amount"] for r in by_provider) == total


def test_services_and_attribution_span_clouds(repo: PostgresRepository) -> None:
    services = {r["service_name"] for r in run_query(repo, "spend_by_service", _params()).rows}
    assert "Amazon Elastic Compute Cloud - Compute" in services  # AWS
    assert "Virtual Machines" in services  # Azure
    assert "Compute Engine" in services  # GCP
    teams = {r["x_team"] for r in run_query(repo, "spend_by_team", _params()).rows}
    assert "web" in teams  # shared team across Azure + GCP
