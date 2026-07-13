"""Approval-workflow orchestration: gather live recommendations, merge persisted decisions.

Recommendations are recomputed every call from routing (findings) + governance (violations),
so their figures stay grounded; the human's decision on each is looked up by stable key. The
`decide` entry point records a decision — intent only, never an action against infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcca.governance.service import evaluate_policies
from mcca.optimization.model import (
    Recommendation,
    merge_decisions,
    recommendation_key,
)
from mcca.optimization.store import get_decisions, record_decision
from mcca.routing.router import route

if TYPE_CHECKING:
    from datetime import date

    from mcca.warehouse.repository import WarehouseRepository


@dataclass(frozen=True)
class ReviewResult:
    recommendations: list[Recommendation]
    counts: dict[str, int]  # status -> count (PROPOSED / APPROVED / DISMISSED / SNOOZED)


def gather_recommendations(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    budget_month: date | None = None,
) -> list[Recommendation]:
    """Live, grounded recommendations from routing findings + governance violations."""
    recs: list[Recommendation] = []

    report = route(repo, start, end, budget_month=budget_month or end)
    for f in report.findings:
        scope = f.service or f.team
        recs.append(
            Recommendation(
                key=recommendation_key("finding", f.kind, scope, f.summary),
                source="finding",
                kind=f.kind,
                severity=f.severity,
                scope=scope,
                amount=f.amount,
                summary=f.summary,
                action=f.recommendation,
            )
        )

    for v in evaluate_policies(repo, start, end):
        recs.append(
            Recommendation(
                key=recommendation_key("policy", v.kind, v.scope, v.summary),
                source="policy",
                kind=v.kind,
                severity=v.severity,
                scope=v.scope,
                amount=v.observed,
                summary=v.summary,
                action=v.recommendation,
            )
        )
    return recs


def review_recommendations(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    budget_month: date | None = None,
) -> ReviewResult:
    """Every current recommendation with its persisted decision status + status counts."""
    recs = gather_recommendations(repo, start, end, budget_month=budget_month)
    decisions = get_decisions(repo, {r.key for r in recs})
    merged, counts = merge_decisions(recs, decisions)
    return ReviewResult(recommendations=merged, counts=counts)


def decide(
    repo: WarehouseRepository,
    start: date,
    end: date,
    rec_key: str,
    status: str,
    *,
    decided_by: str | None = None,
    note: str | None = None,
    snooze_until: date | None = None,
    budget_month: date | None = None,
) -> Recommendation:
    """Record a human decision on a recommendation (matched by key or unique prefix).

    Snapshots the recommendation for audit. Raises if the key matches zero or multiple current
    recommendations. Records intent only — nothing is executed.
    """
    recs = gather_recommendations(repo, start, end, budget_month=budget_month)
    matches = [r for r in recs if r.key == rec_key or r.key.startswith(rec_key)]
    if not matches:
        raise ValueError(f"No current recommendation matches key {rec_key!r}.")
    if len(matches) > 1:
        raise ValueError(
            f"Key {rec_key!r} is ambiguous ({len(matches)} matches); use a longer key."
        )
    rec = matches[0]
    record_decision(
        repo,
        rec.key,
        status,
        decided_by=decided_by,
        note=note,
        snooze_until=snooze_until,
        snapshot=rec,
    )
    from dataclasses import replace

    return replace(rec, status=status, decided_by=decided_by, note=note, snooze_until=snooze_until)
