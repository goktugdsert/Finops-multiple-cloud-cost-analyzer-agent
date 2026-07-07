"""Integration: detection finds the injected spikes and the steady-waste line.

The synthetic generator injects spikes (EC2 x2.5 @ day 38, Data Transfer x6 @ 95,
Lambda x4 @ 150) and a deliberately flat EBS line. Requires `docker compose up -d`.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import OperationalError

from mcca.detection.service import detect
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import metadata

pytestmark = pytest.mark.integration

START = date(2026, 1, 1)
END = date(2026, 7, 1)  # 181 days -> covers injected anomalies at 38/95/150


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


def test_detects_injected_spikes(repo: PostgresRepository) -> None:
    report = detect(repo, START, END, window=14, z=3.0)
    spiked_services = {s.service for s in report.spikes}
    # The big multipliers are unambiguous.
    assert "AWS Data Transfer" in spiked_services  # x6
    assert "AWS Lambda" in spiked_services  # x4
    # Spikes carry a real ratio above baseline.
    assert all(s.ratio > 1.5 for s in report.spikes)


def test_flags_steady_ebs_waste(repo: PostgresRepository) -> None:
    report = detect(repo, START, END)
    steady_services = {c.service for c in report.steady_costs}
    assert "Amazon Elastic Block Store" in steady_services
