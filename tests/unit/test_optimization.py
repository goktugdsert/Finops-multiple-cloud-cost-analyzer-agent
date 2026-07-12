"""Approval-workflow domain: stable keys and correct decision merging (no DB)."""

from __future__ import annotations

from decimal import Decimal

from mcca.optimization.model import (
    PROPOSED,
    Recommendation,
    merge_decisions,
    recommendation_key,
)


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
    merged, counts = merge_decisions(recs, decisions)
    by_key = {m.key: m for m in merged}
    assert by_key["k1"].status == "APPROVED"
    assert by_key["k1"].decided_by == "alice"
    assert by_key["k2"].status == PROPOSED
    assert counts == {"APPROVED": 1, PROPOSED: 1}
