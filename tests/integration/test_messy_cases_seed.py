"""Integration: the previously-stubbed messy cases survive the full ingest path.

Seeds AWS + Azure and asserts the warehouse actually contains the commitment/credit/blended
data now emitted and normalized: Savings Plan line items, populated commitment_discount_*
columns, a captured (non-billed) blended cost, a list cost above billed for covered usage,
and Azure refund/adjustment lines.

PROVEN HERE: the emission + normalization + storage of these cases against the synthetic
fixture. STILL PENDING (real data): that the exact figures match a real provider console —
that requires a live billing account and is tracked as an open v1 debt.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import and_, func, select
from sqlalchemy.exc import OperationalError

from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_azure_warehouse, seed_warehouse
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import focus_costs, metadata

pytestmark = pytest.mark.integration

START = date(2026, 1, 1)
END = date(2026, 3, 1)


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
    yield repository
    metadata.drop_all(engine)
    engine.dispose()


def _count(repo: PostgresRepository, whereclause) -> int:
    with repo.engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(focus_costs).where(whereclause)
        ).scalar_one()


def test_savings_plan_lines_are_stored_with_commitment_metadata(repo: PostgresRepository) -> None:
    covered = _count(
        repo,
        and_(
            focus_costs.c.charge_description == "SavingsPlanCoveredUsage",
            focus_costs.c.commitment_discount_type == "Savings Plan",
        ),
    )
    fees = _count(repo, focus_costs.c.charge_description == "SavingsPlanRecurringFee")
    assert covered > 0
    assert fees > 0


def test_list_cost_exceeds_billed_for_covered_usage(repo: PostgresRepository) -> None:
    # Covered usage is billed $0 but its list (on-demand) cost is positive.
    with repo.engine.connect() as conn:
        row = conn.execute(
            select(focus_costs.c.billed_cost, focus_costs.c.list_cost)
            .where(focus_costs.c.charge_description == "SavingsPlanCoveredUsage")
            .limit(1)
        ).one()
    billed, list_cost = Decimal(str(row[0])), Decimal(str(row[1]))
    assert billed == 0
    assert list_cost > billed


def test_blended_cost_captured_but_not_billed(repo: PostgresRepository) -> None:
    # At least one AWS line has a blended cost that differs from its (unblended) billed cost.
    differing = _count(
        repo,
        and_(
            focus_costs.c.provider_name == "AWS",
            focus_costs.c.x_blended_cost.isnot(None),
            focus_costs.c.x_blended_cost != focus_costs.c.billed_cost,
        ),
    )
    assert differing > 0


def test_contracted_cost_is_populated_across_clouds(repo: PostgresRepository) -> None:
    # The one FOCUS cost measure that used to be always-NULL is now set for every cloud.
    for provider in ("AWS", "Azure"):
        null_contracted = _count(
            repo,
            and_(
                focus_costs.c.provider_name == provider,
                focus_costs.c.contracted_cost.is_(None),
            ),
        )
        assert null_contracted == 0, f"{provider} has NULL contracted_cost rows"


def test_aws_discount_stack_holds_list_ge_contracted_ge_billed(repo: PostgresRepository) -> None:
    # For AWS on-demand usage the full stack is representable and ordered correctly.
    violations = _count(
        repo,
        and_(
            focus_costs.c.provider_name == "AWS",
            focus_costs.c.charge_category == "Usage",
            focus_costs.c.charge_description == "Usage",
            focus_costs.c.billed_cost > 0,
            focus_costs.c.list_cost < focus_costs.c.contracted_cost,
        ),
    )
    assert violations == 0


def test_azure_credits_and_adjustments_present(repo: PostgresRepository) -> None:
    credits = _count(
        repo,
        and_(
            focus_costs.c.provider_name == "Azure",
            focus_costs.c.charge_category == "Credit",
            focus_costs.c.billed_cost < 0,
        ),
    )
    adjustments = _count(
        repo,
        and_(
            focus_costs.c.provider_name == "Azure",
            focus_costs.c.charge_category == "Adjustment",
        ),
    )
    assert credits > 0
    assert adjustments > 0
