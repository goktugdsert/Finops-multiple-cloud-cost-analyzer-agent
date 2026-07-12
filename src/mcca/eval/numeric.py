"""Numeric-faithfulness eval: every fixed query returns the known-correct fixture value.

Because the warehouse is seeded from a deterministic synthetic generator, we KNOW the
ground-truth answer to every query. Here we compute each expected figure a SECOND, fully
independent way — a naive Python aggregation over the raw normalized rows
(``repo.fetch_all()``) — and assert the SQL query layer returns exactly that. Agreement
between two independent computations over the same fixture is the strongest correctness
guarantee available without a real cloud bill to reconcile against.

SCOPE / HONESTY: this proves numeric faithfulness against SYNTHETIC ground truth only — it
shows the query/aggregation logic is self-consistent and matches an independent count of
the same fixture. It does NOT prove the fixture equals a real provider invoice;
reconciliation to a real console remains an open debt requiring a live billing account.

Stochastic tools (forecast) are intentionally excluded — they have prediction intervals,
not a single fixed ground-truth value; their correctness is covered by their own tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from mcca.queries.registry import run_query

if TYPE_CHECKING:
    from mcca.warehouse.repository import WarehouseRepository

Row = dict[str, Any]


@dataclass(frozen=True)
class NumericResult:
    name: str
    passed: bool
    note: str


def _as_date(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


def _in_range(row: Row, start: date, end: date) -> bool:
    day = _as_date(row["charge_period_start"])
    return start <= day < end


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _ground_total(rows: list[Row], start: date, end: date, metric: str) -> Decimal:
    return sum((_dec(r[metric]) for r in rows if _in_range(r, start, end)), Decimal("0"))


def _ground_group(rows: list[Row], field: str, start: date, end: date, metric: str) -> dict:
    out: dict[Any, Decimal] = {}
    for r in rows:
        if _in_range(r, start, end):
            out[r[field]] = out.get(r[field], Decimal("0")) + _dec(r[metric])
    return out


def _ground_daily(rows: list[Row], start: date, end: date, metric: str) -> dict:
    out: dict[date, Decimal] = {}
    for r in rows:
        if _in_range(r, start, end):
            day = _as_date(r["charge_period_start"])
            out[day] = out.get(day, Decimal("0")) + _dec(r[metric])
    return out


def _ground_monthly(rows: list[Row], start: date, end: date, metric: str) -> dict:
    out: dict[date, Decimal] = {}
    for r in rows:
        if _in_range(r, start, end):
            day = _as_date(r["charge_period_start"])
            month = date(day.year, day.month, 1)
            out[month] = out.get(month, Decimal("0")) + _dec(r[metric])
    return out


def _query_map(
    repo: WarehouseRepository, name: str, start: date, end: date, key: str, metric: str
) -> dict:
    rows = run_query(repo, name, {"start": start, "end": end, "metric": metric}).rows
    return {_as_date(r[key]): _dec(r["amount"]) for r in rows}


def _compare(name: str, expected: dict, actual: dict) -> NumericResult:
    if expected == actual:
        return NumericResult(name, True, f"{len(expected)} value(s) match fixture ground truth")
    keys = set(expected) | set(actual)
    diffs = [
        f"{k!r}: expected {expected.get(k)} got {actual.get(k)}"
        for k in keys
        if expected.get(k) != actual.get(k)
    ]
    return NumericResult(name, False, "MISMATCH — " + "; ".join(diffs[:4]))


def run_numeric_checks(
    repo: WarehouseRepository, start: date, end: date, metric: str = "billed_cost"
) -> list[NumericResult]:
    """Assert each fixed query's figures equal an independent aggregation of the fixture."""
    rows = repo.fetch_all()
    results: list[NumericResult] = []

    # total_spend — check BOTH cost measures.
    total = run_query(repo, "total_spend", {"start": start, "end": end}).rows[0]
    expected_total = {
        "billed_cost": _ground_total(rows, start, end, "billed_cost"),
        "effective_cost": _ground_total(rows, start, end, "effective_cost"),
    }
    actual_total = {
        "billed_cost": _dec(total["billed_cost"]),
        "effective_cost": _dec(total["effective_cost"]),
    }
    results.append(_compare("total_spend", expected_total, actual_total))

    # Grouped visibility/attribution queries (query name, output key column, row field).
    group_specs = [
        ("spend_by_service", "service_name", "service_name"),
        ("spend_by_provider", "provider_name", "provider_name"),
        ("spend_by_charge_category", "charge_category", "charge_category"),
        ("spend_by_team", "x_team", "x_team"),
        ("spend_by_environment", "x_environment", "x_environment"),
    ]
    for qname, out_key, field in group_specs:
        expected = _ground_group(rows, field, start, end, metric)
        actual = _query_map(repo, qname, start, end, out_key, metric)
        results.append(_compare(qname, expected, actual))

    # Time series.
    results.append(
        _compare(
            "daily_spend",
            _ground_daily(rows, start, end, metric),
            _query_map(repo, "daily_spend", start, end, "day", metric),
        )
    )
    expected_monthly = _ground_monthly(rows, start, end, metric)
    results.append(
        _compare(
            "monthly_spend",
            expected_monthly,
            _query_map(repo, "monthly_spend", start, end, "month", metric),
        )
    )

    # month_over_month — amounts must equal the independent monthly totals, and each delta
    # must equal the difference from the prior month (first month has a NULL delta).
    mom = run_query(repo, "month_over_month", {"start": start, "end": end, "metric": metric}).rows
    actual_mom = {_as_date(r["month"]): _dec(r["amount"]) for r in mom}
    amounts_ok = actual_mom == expected_monthly
    delta_ok = True
    prev: Decimal | None = None
    for r in sorted(mom, key=lambda x: x["month"]):
        amount = _dec(r["amount"])
        if prev is None:
            delta_ok = delta_ok and r["delta"] is None
        else:
            delta_ok = delta_ok and _dec(r["delta"]) == amount - prev
        prev = amount
    note = (
        f"{len(mom)} month(s): amounts+deltas match fixture"
        if amounts_ok and delta_ok
        else "MISMATCH — monthly amounts or deltas disagree with independent aggregation"
    )
    results.append(NumericResult("month_over_month", amounts_ok and delta_ok, note))

    return results


def main() -> None:
    from mcca.config import get_settings
    from mcca.logging import configure_logging
    from mcca.warehouse.postgres import PostgresRepository

    configure_logging()
    get_settings()
    repo = PostgresRepository()

    bounds = run_query(repo, "charge_date_bounds", {}).rows[0]
    if bounds["min_day"] is None:
        print("No data in warehouse — run `uv run mcca-seed` first.")
        return
    start, end = bounds["min_day"], bounds["max_day"] + timedelta(days=1)

    results = run_numeric_checks(repo, start, end)
    print(f"\nNumeric-faithfulness eval — fixture window {start} .. {end} (exclusive)\n")
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] {r.name:<26} {r.note}")
    passed = sum(r.passed for r in results)
    print(f"\nScore: {passed}/{len(results)} queries return fixture-exact figures")
    print("(Synthetic ground truth only — real-console reconciliation still pending.)")


if __name__ == "__main__":
    main()
