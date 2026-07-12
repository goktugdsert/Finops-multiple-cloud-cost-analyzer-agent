"""The allocation policy splits shared spend deterministically and reconciles to the cent."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mcca.allocation.policy import allocate


def _totals(result) -> dict[str, Decimal]:
    return {t.team: t for t in result.teams}


def test_proportional_splits_by_direct_spend() -> None:
    res = allocate({"platform": Decimal("300"), "data": Decimal("100")}, Decimal("100"))
    t = _totals(res)
    assert res.method == "proportional"
    assert t["platform"].allocated == Decimal("75.00")  # 3/4 of the pool
    assert t["data"].allocated == Decimal("25.00")  # 1/4
    assert t["platform"].total == Decimal("375.00")
    assert res.unallocated == Decimal("0.00")


def test_even_split_ignores_size() -> None:
    res = allocate({"a": Decimal("900"), "b": Decimal("100")}, Decimal("50"), method="even")
    t = _totals(res)
    assert t["a"].allocated == Decimal("25.00")
    assert t["b"].allocated == Decimal("25.00")


def test_weighted_uses_supplied_shares() -> None:
    res = allocate(
        {"a": Decimal("100"), "b": Decimal("100")},
        Decimal("100"),
        method="weighted",
        weights={"a": Decimal("3"), "b": Decimal("1")},
    )
    t = _totals(res)
    assert t["a"].allocated == Decimal("75.00")
    assert t["b"].allocated == Decimal("25.00")


def test_shares_reconcile_to_pool_exactly_despite_rounding() -> None:
    # 3-way split of $100 -> $33.33 each leaves a 1-cent residual; it must not vanish.
    res = allocate({"a": Decimal("1"), "b": Decimal("1"), "c": Decimal("1")}, Decimal("100"))
    allocated = sum((x.allocated for x in res.teams), Decimal("0"))
    assert allocated == Decimal("100.00")  # every cent of the pool is distributed
    assert res.unallocated == Decimal("0.00")


def test_no_attributed_teams_leaves_pool_unallocated() -> None:
    # Nothing to allocate onto -> the pool is surfaced honestly, not guessed away.
    res = allocate({}, Decimal("500"))
    assert res.teams == []
    assert res.unallocated == Decimal("500.00")


def test_zero_direct_total_leaves_pool_unallocated() -> None:
    res = allocate({"a": Decimal("0"), "b": Decimal("0")}, Decimal("80"))
    assert res.unallocated == Decimal("80.00")
    assert all(t.allocated == Decimal("0.00") for t in res.teams)


def test_unknown_method_raises() -> None:
    with pytest.raises(ValueError, match="Unknown allocation method"):
        allocate({"a": Decimal("1")}, Decimal("1"), method="magic")
