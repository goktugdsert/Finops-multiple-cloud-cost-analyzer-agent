"""Approval-workflow domain: stable keys and correct decision merging (no DB)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from mcca.optimization.model import (
    PROPOSED,
    Recommendation,
    merge_decisions,
    recommendation_key,
)

_TODAY = date(2026, 6, 15)


def _rec(key: str, status: str = PROPOSED) -> Recommendation:
    return Recommendation(
        key=key,
        source="finding",
        kind="SPIKE",
        severity="HIGH",
        scope="EC2",
        amount=Decimal("100"),
        summary="s",
        action="a",
        status=status,
    )


def test_recommendation_key_is_stable_and_identity_based() -> None:
    a = recommendation_key("finding", "SPIKE", "EC2", "spiked 4x on 2026-01-04")
    b = recommendation_key("finding", "SPIKE", "EC2", "spiked 4x on 2026-01-04")
    assert a == b  # same identity -> same key across runs
    assert a != recommendation_key("finding", "SPIKE", "S3", "spiked 4x on 2026-01-04")
    assert a != recommendation_key("policy", "SPIKE", "EC2", "spiked 4x on 2026-01-04")


def test_merge_defaults_to_proposed_when_no_decision() -> None:
    recs = [_rec("k1"), _rec("k2")]
    merged, counts = merge_decisions(recs, {})
    assert all(m.status == PROPOSED for m in merged)
    assert counts == {PROPOSED: 2}


def test_merge_applies_persisted_decision() -> None:
    recs = [_rec("k1"), _rec("k2")]
    decisions = {"k1": {"status": "APPROVED", "decided_by": "alice", "note": "ok"}}
    merged, counts = merge_decisions(recs, decisions, today=_TODAY)
    by_key = {m.key: m for m in merged}
    assert by_key["k1"].status == "APPROVED"
    assert by_key["k1"].decided_by == "alice"
    assert by_key["k2"].status == PROPOSED
    assert counts == {"APPROVED": 1, PROPOSED: 1}


def test_active_snooze_hides_the_recommendation() -> None:
    decisions = {"k1": {"status": "SNOOZED", "snooze_until": date(2026, 6, 20)}}  # future
    merged, counts = merge_decisions([_rec("k1")], decisions, today=_TODAY)
    assert merged[0].status == "SNOOZED"
    assert counts == {"SNOOZED": 1}


def test_expired_snooze_re_surfaces_as_proposed() -> None:
    decisions = {"k1": {"status": "SNOOZED", "snooze_until": date(2026, 6, 10)}}  # past
    merged, counts = merge_decisions([_rec("k1")], decisions, today=_TODAY)
    assert merged[0].status == PROPOSED  # snooze expired -> back in the queue
    assert counts == {PROPOSED: 1}


def test_snooze_without_until_stays_snoozed() -> None:
    decisions = {"k1": {"status": "SNOOZED", "snooze_until": None}}
    merged, _ = merge_decisions([_rec("k1")], decisions, today=_TODAY)
    assert merged[0].status == "SNOOZED"
