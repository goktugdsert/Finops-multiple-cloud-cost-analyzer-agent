"""Integration: the governance engine flags real violations from seeded spend (recommend-only).

Thresholds are calibrated from the actual seeded figures so the test is deterministic without
hard-coding dollar amounts. Every violation figure traces to spend_by_team / spend_by_service.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from mcca.governance.policy import DEFAULT_POLICIES, Policy
from mcca.governance.service import evaluate_policies
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.queries.registry import run_query
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import UNATTRIBUTED, metadata

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


def _top_team(repo: PostgresRepository) -> tuple[str, Decimal]:
    rows = run_query(repo, "spend_by_team", {"start": START, "end": END}).rows
    teams = {r["x_team"]: Decimal(str(r["amount"])) for r in rows if r["x_team"] != UNATTRIBUTED}
    name = max(teams, key=lambda t: teams[t])
    return name, teams[name]


def test_team_cap_breach_is_flagged_below_and_clear_above(repo: PostgresRepository) -> None:
    name, amount = _top_team(repo)

    below = Policy("cap-low", "team_cap", {"max_amount": int(amount) - 1}, "HIGH")
    breaches = evaluate_policies(repo, START, END, policies=[below])
    assert any(
        v.scope == name and v.observed.quantize(Decimal("1")) == amount.quantize(Decimal("1"))
        for v in breaches
    )

    above = Policy("cap-high", "team_cap", {"max_amount": int(amount) + 1}, "HIGH")
    assert evaluate_policies(repo, START, END, policies=[above]) == []


def test_denied_service_flags_a_real_service(repo: PostgresRepository) -> None:
    rows = run_query(repo, "spend_by_service", {"start": START, "end": END, "limit": 1}).rows
    top_service = rows[0]["service_name"]
    policy = Policy("deny-top", "denied_service", {"services": [top_service]}, "LOW")
    vs = evaluate_policies(repo, START, END, policies=[policy])
    assert [v.scope for v in vs] == [top_service]


def test_default_policy_set_runs_and_is_recommend_only(repo: PostgresRepository) -> None:
    vs = evaluate_policies(repo, START, END, policies=DEFAULT_POLICIES)
    # Runs cleanly and every violation carries a recommended action (nothing is enforced).
    assert all(v.recommendation for v in vs)


def test_stored_policies_are_configurable(repo: PostgresRepository) -> None:
    from mcca.governance.policy import Policy
    from mcca.governance.store import get_policies, seed_default_policies, upsert_policy

    assert get_policies(repo) == []  # create_all leaves the table empty until seeded
    assert seed_default_policies(repo) == len(DEFAULT_POLICIES)
    assert {p.id for p in get_policies(repo)} == {p.id for p in DEFAULT_POLICIES}

    # evaluate() with no explicit policies now uses the STORED set (seeded above).
    assert all(v.recommendation for v in evaluate_policies(repo, START, END))

    # Add a strict custom policy -> a new violation appears, driven by stored config.
    upsert_policy(repo, Policy("strict-untagged", "untagged_limit", {"max_fraction": 0.001}, "HIGH"))
    vs = evaluate_policies(repo, START, END)
    assert any(v.policy_id == "strict-untagged" for v in vs)

    # Disabling a policy removes it from evaluation.
    upsert_policy(repo, Policy("strict-untagged", "untagged_limit", {"max_fraction": 0.001}), enabled=False)
    vs2 = evaluate_policies(repo, START, END)
    assert not any(v.policy_id == "strict-untagged" for v in vs2)
