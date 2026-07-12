"""Governance orchestration: pull grounded spend, then evaluate the policy set.

Team and service spend come from the fixed queries, so violation figures are traceable to a
validated query — the engine only compares them to declarative thresholds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcca.governance.policy import DEFAULT_POLICIES, Policy, Violation, evaluate_over_rows
from mcca.governance.store import get_policies
from mcca.queries.registry import run_query

if TYPE_CHECKING:
    from datetime import date

    from mcca.warehouse.repository import WarehouseRepository


def evaluate_policies(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    policies: list[Policy] | None = None,
    metric: str = "billed_cost",
) -> list[Violation]:
    """Evaluate the governance policy set against spend over [start, end). Recommend-only.

    When `policies` is not given, load the org's stored policies; if none are stored, fall
    back to the illustrative DEFAULT_POLICIES.
    """
    if policies is None:
        policies = get_policies(repo) or DEFAULT_POLICIES
    window = {"start": start, "end": end, "metric": metric}
    team_rows = run_query(repo, "spend_by_team", window).rows
    service_rows = run_query(repo, "spend_by_service", window).rows
    return evaluate_over_rows(policies, team_rows, service_rows)
