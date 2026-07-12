"""Governance policies + a deterministic evaluator (recommend-only).

Policies are declarative DATA (a kind + parameters), not code. Each evaluator is a pure
function over grounded query results (spend_by_team / spend_by_service), so every figure a
violation reports is traceable to a validated query — never invented by an LLM. The engine
FLAGS violations with a recommended action; it never enforces or changes anything (a human
acts). This is a v2 capability; DEFAULT_POLICIES below is illustrative — real orgs configure
their own set.

Policy kinds:
  - untagged_limit  {max_fraction}      unattributed spend must stay under a % of total.
  - team_cap        {max_amount, team?} no team (or a named team) may exceed a $ cap.
  - denied_service  {services: [...]}   spend on a restricted service is not allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from mcca.warehouse.schema import UNATTRIBUTED

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class Policy:
    id: str
    kind: str
    params: dict[str, Any]
    severity: str = "MEDIUM"
    description: str = ""


@dataclass(frozen=True)
class Violation:
    policy_id: str
    kind: str
    severity: str
    scope: str  # what the violation is about (team / service / "unattributed")
    observed: Decimal  # the measured value that breached the policy
    threshold: Decimal  # the policy limit
    summary: str
    recommendation: str


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _team_map(team_rows: list[dict[str, Any]]) -> dict[str, Decimal]:
    return {r["x_team"]: _dec(r["amount"]) for r in team_rows}


def _service_map(service_rows: list[dict[str, Any]]) -> dict[str, Decimal]:
    return {r["service_name"]: _dec(r["amount"]) for r in service_rows}


def _eval_untagged_limit(
    p: Policy, team_rows: list[dict[str, Any]], service_rows: list[dict[str, Any]]
) -> list[Violation]:
    teams = _team_map(team_rows)
    total = sum(teams.values(), Decimal("0"))
    if total <= 0:
        return []
    untagged = teams.get(UNATTRIBUTED, Decimal("0"))
    max_fraction = _dec(p.params["max_fraction"])
    if untagged / total <= max_fraction:
        return []
    pct = (untagged / total * 100).quantize(Decimal("0.1"))
    return [
        Violation(
            p.id,
            p.kind,
            p.severity,
            UNATTRIBUTED,
            untagged.quantize(_CENTS),
            max_fraction,
            f"Unattributed spend is {pct}% of total (policy limit {max_fraction * 100:.0f}%).",
            "Tag the untagged resources (team/owner) to bring attribution above the floor.",
        )
    ]


def _eval_team_cap(
    p: Policy, team_rows: list[dict[str, Any]], service_rows: list[dict[str, Any]]
) -> list[Violation]:
    teams = _team_map(team_rows)
    cap = _dec(p.params["max_amount"])
    target = p.params.get("team")
    names = [target] if target else [t for t in teams if t != UNATTRIBUTED]
    out: list[Violation] = []
    for name in names:
        amount = teams.get(name, Decimal("0"))
        if amount > cap:
            out.append(
                Violation(
                    p.id,
                    p.kind,
                    p.severity,
                    name,
                    amount.quantize(_CENTS),
                    cap,
                    f"Team '{name}' spend ${amount:,.0f} exceeds the ${cap:,.0f} cap.",
                    f"Review '{name}' spend vs its budget and investigate the largest drivers.",
                )
            )
    return out


def _eval_denied_service(
    p: Policy, team_rows: list[dict[str, Any]], service_rows: list[dict[str, Any]]
) -> list[Violation]:
    services = _service_map(service_rows)
    out: list[Violation] = []
    for svc in p.params.get("services", []):
        amount = services.get(svc, Decimal("0"))
        if amount > 0:
            out.append(
                Violation(
                    p.id,
                    p.kind,
                    p.severity,
                    svc,
                    amount.quantize(_CENTS),
                    Decimal("0"),
                    f"Spend on restricted service '{svc}' is ${amount:,.0f} (policy: not allowed).",
                    f"Confirm '{svc}' is approved; if not, migrate off it or request an exception.",
                )
            )
    return out


_EVALUATORS = {
    "untagged_limit": _eval_untagged_limit,
    "team_cap": _eval_team_cap,
    "denied_service": _eval_denied_service,
}


def evaluate_over_rows(
    policies: list[Policy],
    team_rows: list[dict[str, Any]],
    service_rows: list[dict[str, Any]],
) -> list[Violation]:
    """Evaluate every policy against grounded rows, returning violations (most severe first)."""
    violations: list[Violation] = []
    for p in policies:
        evaluator = _EVALUATORS.get(p.kind)
        if evaluator is None:
            raise ValueError(f"Unknown policy kind {p.kind!r}; known: {sorted(_EVALUATORS)}")
        violations.extend(evaluator(p, team_rows, service_rows))
    violations.sort(key=lambda v: (SEVERITY_ORDER.get(v.severity, 9), -v.observed))
    return violations


# Illustrative default policy set (real orgs configure their own).
DEFAULT_POLICIES: list[Policy] = [
    Policy(
        "untagged-under-10pct",
        "untagged_limit",
        {"max_fraction": 0.10},
        "HIGH",
        "Keep unattributed spend under 10% of total.",
    ),
    Policy(
        "no-team-over-100k",
        "team_cap",
        {"max_amount": 100000},
        "MEDIUM",
        "No single team should exceed $100k over the period.",
    ),
    Policy(
        "egress-governed",
        "denied_service",
        {"services": ["AWS Data Transfer"]},
        "LOW",
        "Data-transfer/egress spend is governed and must be approved.",
    ),
]
