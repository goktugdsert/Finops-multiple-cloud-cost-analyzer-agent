"""Route findings to owners with recommended (never executed) actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from mcca.budgets.service import spend_vs_budget
from mcca.detection.service import detect
from mcca.queries.registry import run_query
from mcca.warehouse.schema import UNATTRIBUTED

if TYPE_CHECKING:
    from mcca.budgets.model import BudgetStatus
    from mcca.detection.detector import Spike, SteadyCost
    from mcca.warehouse.repository import WarehouseRepository

_SEVERITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


@dataclass(frozen=True)
class Finding:
    kind: str  # SPIKE | WASTE | BUDGET
    severity: str  # HIGH | MEDIUM | LOW
    service: str | None
    team: str
    owner: str
    amount: Decimal  # $ associated with the finding
    summary: str  # what was found (deterministic, with numbers)
    recommendation: str  # recommended action (templated; a human approves)


@dataclass(frozen=True)
class RoutingReport:
    findings: list[Finding]


def build_findings(
    spikes: list[Spike],
    steady_costs: list[SteadyCost],
    budget_status: BudgetStatus | None,
    owners: dict[str, tuple[str, str]],
) -> list[Finding]:
    """Turn detection + budget results into owner-routed recommendations (pure)."""
    findings: list[Finding] = []

    for s in spikes:
        team, owner = owners.get(s.service, (UNATTRIBUTED, "unassigned"))
        severity = "HIGH" if s.ratio >= 4 else "MEDIUM" if s.ratio >= 2 else "LOW"
        findings.append(
            Finding(
                kind="SPIKE",
                severity=severity,
                service=s.service,
                team=team,
                owner=owner,
                amount=s.amount,
                summary=f"{s.service} spend spiked {s.ratio:.1f}x on {s.date} (${s.amount}).",
                recommendation=(
                    f"Investigate the {s.service} spike on {s.date}: check for runaway "
                    "autoscaling, a misconfiguration, or a one-off job."
                ),
            )
        )

    for c in steady_costs:
        team, owner = owners.get(c.service, (UNATTRIBUTED, "unassigned"))
        severity = "MEDIUM" if c.monthly_estimate >= Decimal("100") else "LOW"
        findings.append(
            Finding(
                kind="WASTE",
                severity=severity,
                service=c.service,
                team=team,
                owner=owner,
                amount=c.monthly_estimate,
                summary=f"{c.service} shows steady ~${c.monthly_estimate}/mo with flat usage.",
                recommendation=(
                    f"Review {c.service} for rightsizing, idle/unattached resources, or "
                    "scheduling to cut structural waste."
                ),
            )
        )

    if budget_status is not None and budget_status.status in ("OVER", "AT_RISK"):
        severity = "HIGH" if budget_status.status == "OVER" else "MEDIUM"
        findings.append(
            Finding(
                kind="BUDGET",
                severity=severity,
                service=None,
                team="finops",
                owner="budget-owner",
                amount=budget_status.variance,
                summary=(
                    f"{budget_status.month:%b %Y} projected ${budget_status.projected} vs "
                    f"${budget_status.budget_amount} budget "
                    f"({budget_status.variance_pct:+.1f}%)."
                ),
                recommendation=(
                    "Review the forecast drivers and consider commitments (RIs/Savings "
                    "Plans) or scaling limits to bring the month back within budget."
                ),
            )
        )

    findings.sort(key=lambda f: (_SEVERITY_RANK[f.severity], -abs(f.amount)))
    return findings


def _owner_map(
    repo: WarehouseRepository, start: date, end: date, metric: str
) -> dict[str, tuple[str, str]]:
    """Dominant (team, owner) per service, by spend, from usage lines."""
    rows = run_query(
        repo,
        "service_owners",
        {"start": start, "end": end, "metric": metric, "charge_category": "Usage"},
    ).rows
    owners: dict[str, tuple[str, str]] = {}
    best: dict[str, Decimal] = {}
    for r in rows:
        service = r["service_name"]
        billed = Decimal(str(r["billed"]))
        if service not in best or billed > best[service]:
            best[service] = billed
            owners[service] = (r["x_team"], r["x_owner"])
    return owners


def route(
    repo: WarehouseRepository,
    start: date,
    end: date,
    *,
    budget_month: date | None = None,
    metric: str = "billed_cost",
) -> RoutingReport:
    """Gather findings over [start, end), route each to an owner with an action."""
    detection = detect(repo, start, end)
    budget_status = spend_vs_budget(repo, budget_month) if budget_month else None
    owners = _owner_map(repo, start, end, metric)
    return RoutingReport(
        build_findings(detection.spikes, detection.steady_costs, budget_status, owners)
    )
