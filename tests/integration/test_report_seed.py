"""Integration: build the HTML report from real seeded data.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import OperationalError

from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.surface.report import build_report_data, render_html
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


def test_report_builds_from_seeded_data(repo: PostgresRepository) -> None:
    data = build_report_data(repo, START, END, horizon=30)
    assert data["total_billed"] > 0
    assert data["total_effective"] < data["total_billed"]  # amortization savings
    assert len(data["months"]) == 3
    assert data["forecast"]["hi"] > data["forecast"]["mid"] > data["forecast"]["lo"]

    html = render_html(data)
    assert "<svg" in html
    assert "Amazon Elastic Compute Cloud - Compute" in html
