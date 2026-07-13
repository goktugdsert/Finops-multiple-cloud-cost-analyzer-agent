"""Read/write governance policies (config-like data) — same pattern as budgets/store.py.

Policies are stored so an org configures its own rules; the engine loads them from here. This
writes only the `policies` config table, never the FOCUS cost data or infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, insert, select, update

from mcca.governance.policy import DEFAULT_POLICIES, Policy
from mcca.warehouse.schema import policies as policies_table

if TYPE_CHECKING:
    from mcca.warehouse.repository import WarehouseRepository

_REQUIRED = ("policy_id", "kind", "params", "severity")


def get_policies(repo: WarehouseRepository, *, enabled_only: bool = True) -> list[Policy]:
    """Load stored policies. Rows not shaped like a policy are skipped (never raises)."""
    out: list[Policy] = []
    for r in repo.execute(select(policies_table)):
        if not all(k in r for k in _REQUIRED):
            continue
        if enabled_only and r.get("enabled") is False:
            continue
        out.append(
            Policy(
                id=r["policy_id"],
                kind=r["kind"],
                params=dict(r["params"]),
                severity=r["severity"],
                description=r.get("description") or "",
            )
        )
    return out


def upsert_policy(repo: WarehouseRepository, policy: Policy, *, enabled: bool = True) -> None:
    """Insert or update a policy by its policy_id."""
    values = {
        "kind": policy.kind,
        "params": policy.params,
        "severity": policy.severity,
        "description": policy.description,
        "enabled": enabled,
        "updated_at": func.now(),
    }
    existing = repo.execute(
        select(policies_table.c.id).where(policies_table.c.policy_id == policy.id)
    )
    if existing:
        repo.execute(
            update(policies_table).where(policies_table.c.policy_id == policy.id).values(**values)
        )
    else:
        repo.execute(insert(policies_table).values(policy_id=policy.id, **values))


def seed_default_policies(repo: WarehouseRepository) -> int:
    """Seed the illustrative DEFAULT_POLICIES once; leaves existing (user-edited) rows alone."""
    if get_policies(repo, enabled_only=False):
        return 0
    for policy in DEFAULT_POLICIES:
        upsert_policy(repo, policy)
    return len(DEFAULT_POLICIES)
