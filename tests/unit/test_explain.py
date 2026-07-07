"""explain_change decomposes a spend change into per-service drivers (no DB)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from mcca.analysis.drivers import explain_change


class TwoPeriodRepo:
    """Fake repo: returns per-service rows keyed by the query's date window."""

    def __init__(self, current: dict[str, str], prior: dict[str, str]) -> None:
        self._current = current
        self._prior = prior

    def execute(self, statement: Any) -> list[dict[str, Any]]:
        # Distinguish the two calls by the prior window's start (only in the prior query).
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        data = self._prior if "2026-04-01" in sql else self._current
        return [{"service_name": k, "amount": Decimal(v)} for k, v in data.items()]

    def create_schema(self) -> None: ...
    def insert_records(self, records: Any) -> int: ...
    def fetch_all(self) -> list[dict[str, Any]]: ...


def test_ranks_drivers_by_absolute_change() -> None:
    repo = TwoPeriodRepo(
        current={"EC2": "1200", "S3": "300", "Lambda": "50"},
        prior={"EC2": "1000", "S3": "320", "Lambda": "20"},
    )
    exp = explain_change(
        repo,
        date(2026, 5, 1),
        date(2026, 6, 1),
        prior_start=date(2026, 4, 1),
        prior_end=date(2026, 5, 1),
    )
    # EC2 moved most (+200), then Lambda (+30), then S3 (-20).
    assert [d.service for d in exp.drivers] == ["EC2", "Lambda", "S3"]
    assert exp.drivers[0].delta == Decimal("200")
    assert exp.total_delta == Decimal("210")  # (1550) - (1340)


def test_new_and_dropped_services_handled() -> None:
    repo = TwoPeriodRepo(current={"EC2": "100", "NEW": "80"}, prior={"EC2": "100", "OLD": "40"})
    exp = explain_change(
        repo,
        date(2026, 5, 1),
        date(2026, 6, 1),
        prior_start=date(2026, 4, 1),
        prior_end=date(2026, 5, 1),
    )
    deltas = {d.service: d.delta for d in exp.drivers}
    assert deltas["NEW"] == Decimal("80")  # appeared
    assert deltas["OLD"] == Decimal("-40")  # disappeared
