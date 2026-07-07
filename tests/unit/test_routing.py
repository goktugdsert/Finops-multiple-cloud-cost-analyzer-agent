"""build_findings routes spikes/waste/budget to owners with recommendations (no DB)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from mcca.budgets.model import evaluate_budget
from mcca.detection.detector import Spike, SteadyCost
from mcca.routing.router import build_findings

OWNERS = {
    "Amazon EC2": ("platform", "alice"),
    "Amazon Elastic Block Store": ("unattributed", "unassigned"),
}


def _spike(service: str, ratio: float) -> Spike:
    return Spike(date(2026, 3, 5), service, Decimal("500"), Decimal("100"), ratio)


def test_spike_severity_and_owner_routing() -> None:
    findings = build_findings([_spike("Amazon EC2", 5.0)], [], None, OWNERS)
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "SPIKE"
    assert f.severity == "HIGH"  # ratio >= 4
    assert (f.team, f.owner) == ("platform", "alice")
    assert "Investigate" in f.recommendation


def test_unmapped_service_is_unassigned() -> None:
    waste = SteadyCost("Amazon Elastic Block Store", Decimal("120"), Decimal("120"), 0.01, 0.0)
    findings = build_findings([], [waste], None, OWNERS)
    assert findings[0].kind == "WASTE"
    assert findings[0].owner == "unassigned"
    assert findings[0].severity == "MEDIUM"  # >= $100/mo


def test_budget_breach_becomes_high_finding() -> None:
    status = evaluate_budget(
        date(2026, 6, 1),
        "total:all",
        Decimal("9000"),
        Decimal("0"),
        Decimal("10500"),
        Decimal("9000"),
        Decimal("12000"),
    )
    findings = build_findings([], [], status, {})
    assert any(f.kind == "BUDGET" and f.severity == "HIGH" for f in findings)


def test_findings_sorted_by_severity() -> None:
    spikes = [_spike("Amazon EC2", 5.0), _spike("Amazon EC2", 1.6)]  # HIGH then LOW
    findings = build_findings(spikes, [], None, OWNERS)
    assert [f.severity for f in findings] == ["HIGH", "LOW"]
