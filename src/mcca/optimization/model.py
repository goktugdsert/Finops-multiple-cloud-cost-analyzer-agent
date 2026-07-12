"""Unified recommendation + its decision status (the approval workflow's domain model).

A `Recommendation` is a live, grounded proposal (from routing findings or governance
violations) with a stable `key`. A human's DECISION on it (approve / dismiss / snooze) is
persisted separately; here we only carry the merged status. Nothing in this workflow acts on
infrastructure — a decision records intent only.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal

# The default state of a live recommendation with no decision yet, plus the states a human
# can record. PROPOSED is never stored — it's the absence of a decision.
PROPOSED = "PROPOSED"
DECISION_STATUSES: tuple[str, ...] = ("APPROVED", "DISMISSED", "SNOOZED")


@dataclass(frozen=True)
class Recommendation:
    key: str
    source: str  # "finding" | "policy"
    kind: str
    severity: str
    scope: str
    amount: Decimal | None
    summary: str
    action: str
    status: str = PROPOSED
    decided_by: str | None = None
    note: str | None = None


def recommendation_key(source: str, kind: str, scope: str, summary: str) -> str:
    """Stable short id for a recommendation, so its decision persists across recomputes.

    Built from the recommendation's identity (source/kind/scope/summary), NOT any volatile
    ordering — the same underlying finding maps to the same key run after run.
    """
    raw = f"{source}|{kind}|{scope}|{summary}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def merge_decisions(
    recommendations: list[Recommendation], decisions: dict[str, dict]
) -> tuple[list[Recommendation], dict[str, int]]:
    """Attach each recommendation's persisted decision (default PROPOSED) and count statuses."""
    merged: list[Recommendation] = []
    for rec in recommendations:
        decision = decisions.get(rec.key)
        if decision is None:
            merged.append(rec)
        else:
            merged.append(
                replace(
                    rec,
                    status=decision["status"],
                    decided_by=decision.get("decided_by"),
                    note=decision.get("note"),
                )
            )
    counts = dict(Counter(m.status for m in merged))
    return merged, counts
