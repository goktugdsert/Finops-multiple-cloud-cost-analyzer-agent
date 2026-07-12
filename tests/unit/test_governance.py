"""The governance evaluators flag violations deterministically from grounded rows (no DB)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mcca.governance.policy import (
    DEFAULT_POLICIES,
    Policy,
    evaluate_over_rows,
)

TEAM_ROWS = [
    {"x_team": "platform", "amount": Decimal("120000")},
    {"x_team": "data", "amount": Decimal("60000")},
    {"x_team": "unattributed", "amount": Decimal("20000")},  # 20k of 200k = 10%
]
SERVICE_ROWS = [
    {"service_name": "Amazon EC2", "amount": Decimal("90000")},
    {"service_name": "AWS Data Transfer", "amount": Decimal("5000")},
]


def _policy(kind: str, params: dict, severity: str = "MEDIUM") -> Policy:
    return Policy(f"p-{kind}", kind, params, severity)


def test_untagged_over_limit_is_flagged() -> None:
    # 10% untagged, limit 8% -> violation.
    vs = evaluate_over_rows([_policy("untagged_limit", {"max_fraction": 0.08})], TEAM_ROWS, [])
    assert len(vs) == 1
    assert vs[0].scope == "unattributed"
    assert vs[0].observed == Decimal("20000.00")


def test_untagged_within_limit_passes() -> None:
    vs = evaluate_over_rows([_policy("untagged_limit", {"max_fraction": 0.15})], TEAM_ROWS, [])
    assert vs == []


def test_team_cap_flags_only_teams_over_the_cap() -> None:
    vs = evaluate_over_rows([_policy("team_cap", {"max_amount": 100000})], TEAM_ROWS, [])
    scopes = {v.scope for v in vs}
    assert scopes == {"platform"}  # platform 120k > 100k; data 60k ok; unattributed excluded


def test_team_cap_can_target_a_single_team() -> None:
    vs = evaluate_over_rows(
        [_policy("team_cap", {"max_amount": 50000, "team": "data"})], TEAM_ROWS, []
    )
    assert [v.scope for v in vs] == ["data"]


def test_denied_service_flags_present_spend() -> None:
    vs = evaluate_over_rows(
        [_policy("denied_service", {"services": ["AWS Data Transfer", "Nonexistent"]})],
        [],
        SERVICE_ROWS,
    )
    assert [v.scope for v in vs] == ["AWS Data Transfer"]  # only the one with spend


def test_violations_sorted_most_severe_first() -> None:
    policies = [
        _policy("denied_service", {"services": ["AWS Data Transfer"]}, "LOW"),
        _policy("team_cap", {"max_amount": 100000}, "HIGH"),
    ]
    vs = evaluate_over_rows(policies, TEAM_ROWS, SERVICE_ROWS)
    assert [v.severity for v in vs] == ["HIGH", "LOW"]


def test_unknown_policy_kind_raises() -> None:
    with pytest.raises(ValueError, match="Unknown policy kind"):
        evaluate_over_rows([_policy("teleport", {})], TEAM_ROWS, SERVICE_ROWS)


def test_default_policies_evaluate_without_error() -> None:
    vs = evaluate_over_rows(DEFAULT_POLICIES, TEAM_ROWS, SERVICE_ROWS)
    # Default set: team cap (platform 120k>100k) + egress present; untagged exactly 10% is OK.
    kinds = {v.kind for v in vs}
    assert "team_cap" in kinds
    assert "denied_service" in kinds
