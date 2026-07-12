"""Cost-allocation policy: redistribute shared/'unattributed' spend onto attributed teams.

The warehouse stays honest — untagged/shared spend is stored as 'unattributed' and is never
mutated. Allocation is a DERIVED, deterministic calculation over a grounded query result
(spend_by_team): it splits the shared pool across the teams that DO have direct spend, so
each team can see a fully-loaded cost.

Methods:
  - proportional: split by each team's direct spend (the FinOps default — "spread by usage").
  - even:         equal split across attributed teams.
  - weighted:     split by caller-supplied fixed shares.

Allocated shares always reconcile to the pool EXACTLY: shares are quantized to cents and the
rounding residual lands on the largest-weight team, so no cent is lost or invented — the core
"provably correct numbers" bar holds. If there is no basis to allocate (no attributed teams,
or a zero/negative weight total), the pool is returned as `unallocated` rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CENTS = Decimal("0.01")

METHODS: tuple[str, ...] = ("proportional", "even", "weighted")


@dataclass(frozen=True)
class TeamAllocation:
    team: str
    direct: Decimal  # the team's own tagged spend
    allocated: Decimal  # its share of the shared pool
    total: Decimal  # direct + allocated (fully-loaded)


@dataclass(frozen=True)
class AllocationResult:
    method: str
    shared_pool: Decimal  # the 'unattributed' amount being distributed
    unallocated: Decimal  # pool left undistributed (no basis to allocate)
    teams: list[TeamAllocation]


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _distribute(
    pool_cents: Decimal, weight_of: dict[str, Decimal], keys: list[str]
) -> dict[str, Decimal]:
    """Split a cent-quantized `pool_cents` across `keys` in proportion to `weight_of`.

    Assumes the weight total is positive (callers guard that). Shares are quantized to cents
    and the whole-cent residual is assigned to the largest-weight team, so the shares sum to
    `pool_cents` EXACTLY — no cent is lost or invented.
    """
    total = sum((weight_of[k] for k in keys), Decimal("0"))
    shares: dict[str, Decimal] = {}
    running = Decimal("0.00")
    for k in keys:
        share = _q(pool_cents * weight_of[k] / total)
        shares[k] = share
        running += share
    top = max(keys, key=lambda k: weight_of[k])
    shares[top] = shares[top] + (pool_cents - running)  # residual is a whole number of cents
    return shares


def allocate(
    direct: dict[str, Decimal],
    pool: Decimal,
    *,
    method: str = "proportional",
    weights: dict[str, Decimal] | None = None,
) -> AllocationResult:
    """Distribute the shared `pool` across teams with `direct` spend, per `method`.

    Works in cents throughout so the invariant `Σ team.direct + shared_pool ==
    Σ team.total + unallocated` holds exactly.
    """
    if method not in METHODS:
        raise ValueError(f"Unknown allocation method {method!r}; choose from {list(METHODS)}")

    pool_cents = _q(pool)
    direct_cents = {k: _q(v) for k, v in direct.items()}
    keys = sorted(direct_cents)

    if method == "proportional":
        weight_of = dict(direct_cents)
    elif method == "even":
        weight_of = {k: Decimal("1") for k in keys}
    else:  # weighted
        weight_of = {k: Decimal(str((weights or {}).get(k, 0))) for k in keys}

    weight_total = sum((weight_of[k] for k in keys), Decimal("0"))
    if not keys or weight_total <= 0:
        # No basis to allocate — keep the pool honestly unallocated, allocate nothing.
        teams = [TeamAllocation(k, direct_cents[k], Decimal("0.00"), direct_cents[k]) for k in keys]
        return AllocationResult(method, pool_cents, pool_cents, teams)

    shares = _distribute(pool_cents, weight_of, keys)
    teams = [
        TeamAllocation(k, direct_cents[k], shares[k], direct_cents[k] + shares[k]) for k in keys
    ]
    return AllocationResult(method, pool_cents, Decimal("0.00"), teams)
