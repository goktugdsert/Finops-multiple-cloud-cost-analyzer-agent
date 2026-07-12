"""Integration: the approval workflow persists human decisions on live recommendations.

Recommendations are recomputed each call from routing + governance; a decision (approve /
dismiss) is stored and re-surfaces on the same recommendation. Nothing is executed — a
decision records intent only.

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.optimization.service import decide, review_recommendations
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import metadata

pytestmark = pytest.mark.integration

START = date(2026, 1, 1)
END = date(2026, 4, 1)


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
    seed_warehouse(repository, START, END, config=GeneratorConfig(seed=42))
    yield repository
    metadata.drop_all(engine)
    engine.dispose()


def test_recommendations_start_proposed(repo: PostgresRepository) -> None:
    result = review_recommendations(repo, START, END)
    assert result.recommendations  # seeded data yields real findings + violations
    assert all(r.status == "PROPOSED" for r in result.recommendations)
    assert result.counts.get("PROPOSED") == len(result.recommendations)


def test_decision_persists_and_re_surfaces(repo: PostgresRepository) -> None:
    target = review_recommendations(repo, START, END).recommendations[0]

    decided = decide(repo, START, END, target.key, "APPROVED", decided_by="alice", note="ack")
    assert decided.status == "APPROVED"

    after = review_recommendations(repo, START, END)
    by_key = {r.key: r for r in after.recommendations}
    assert by_key[target.key].status == "APPROVED"
    assert by_key[target.key].decided_by == "alice"
    assert after.counts.get("APPROVED") == 1
    # Everything else stays proposed.
    assert after.counts.get("PROPOSED") == len(after.recommendations) - 1


def test_decision_is_idempotent_update_not_duplicate(repo: PostgresRepository) -> None:
    target = review_recommendations(repo, START, END).recommendations[0]
    decide(repo, START, END, target.key, "APPROVED")
    decide(repo, START, END, target.key, "DISMISSED")  # change the decision

    after = review_recommendations(repo, START, END)
    by_key = {r.key: r for r in after.recommendations}
    assert by_key[target.key].status == "DISMISSED"
    assert after.counts.get("APPROVED", 0) == 0  # not two rows; the decision was updated


def test_snooze_expiry_round_trip(repo: PostgresRepository) -> None:
    target = review_recommendations(repo, START, END).recommendations[0]

    # Snooze until yesterday -> already expired -> re-surfaces as PROPOSED.
    decide(repo, START, END, target.key, "SNOOZED", snooze_until=date.today() - timedelta(days=1))
    reopened = {r.key: r for r in review_recommendations(repo, START, END).recommendations}
    assert reopened[target.key].status == "PROPOSED"

    # Snooze until tomorrow -> still active -> hidden as SNOOZED.
    decide(repo, START, END, target.key, "SNOOZED", snooze_until=date.today() + timedelta(days=1))
    active = {r.key: r for r in review_recommendations(repo, START, END).recommendations}
    assert active[target.key].status == "SNOOZED"


def test_invalid_and_unknown_decisions_rejected(repo: PostgresRepository) -> None:
    key = review_recommendations(repo, START, END).recommendations[0].key
    with pytest.raises(ValueError, match="Invalid decision"):
        decide(repo, START, END, key, "MAYBE")
    with pytest.raises(ValueError, match="No current recommendation"):
        decide(repo, START, END, "zzzzzzzzzzzz", "APPROVED")
