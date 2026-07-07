"""The fixed query layer validates inputs, builds statements, and carries provenance.

No database: builders are compiled to SQL and inspected; run_query is exercised with a
fake repository that just records the statement it was handed.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Executable

from mcca.queries.registry import (
    get_query,
    list_queries,
    run_query,
    validate_params,
)

EXPECTED_QUERIES = {
    "total_spend",
    "spend_by_service",
    "spend_by_provider",
    "spend_by_charge_category",
    "daily_spend",
    "monthly_spend",
    "daily_spend_by_service",
    "charge_date_bounds",
    "service_owners",
    "spend_by_team",
    "spend_by_environment",
    "month_over_month",
}


class RecordingRepo:
    """Fake repository capturing the statement and returning canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.statement: Executable | None = None
        self._rows = rows or [{"amount": 1}]

    def execute(self, statement: Executable) -> list[dict[str, Any]]:
        self.statement = statement
        return self._rows

    # Unused abstract methods for this test.
    def create_schema(self) -> None: ...
    def insert_records(self, records: Any) -> int: ...
    def fetch_all(self) -> list[dict[str, Any]]: ...


def test_all_expected_queries_registered() -> None:
    assert {q.name for q in list_queries()} == EXPECTED_QUERIES


def test_unknown_query_raises_with_helpful_message() -> None:
    with pytest.raises(KeyError, match="Unknown query 'nope'"):
        get_query("nope")


def test_missing_required_param_raises() -> None:
    defn = get_query("total_spend")
    with pytest.raises(ValueError, match="Missing required parameter 'start'"):
        validate_params(defn, {"end": date(2026, 1, 1)})


def test_unknown_param_rejected() -> None:
    defn = get_query("total_spend")
    with pytest.raises(ValueError, match="Unknown parameter"):
        validate_params(defn, {"start": date(2026, 1, 1), "end": date(2026, 2, 1), "evil": 1})


def test_metric_choice_enforced_and_defaulted() -> None:
    defn = get_query("spend_by_service")
    with pytest.raises(ValueError, match="Invalid value"):
        validate_params(defn, {"start": "2026-01-01", "end": "2026-02-01", "metric": "hax"})
    ok = validate_params(defn, {"start": "2026-01-01", "end": "2026-02-01"})
    assert ok["metric"] == "billed_cost"  # default filled


def test_iso_date_strings_are_coerced() -> None:
    defn = get_query("total_spend")
    resolved = validate_params(defn, {"start": "2026-01-01", "end": "2026-02-01"})
    assert resolved["start"] == date(2026, 1, 1)
    assert resolved["end"] == date(2026, 2, 1)


def test_builders_compile_over_focus_costs() -> None:
    for defn in list_queries():
        # Supply only the params this query declares (some, like charge_date_bounds,
        # take none).
        supplied = {}
        declared = {p.name for p in defn.params}
        if "start" in declared:
            supplied["start"] = date(2026, 1, 1)
        if "end" in declared:
            supplied["end"] = date(2026, 2, 1)
        params = validate_params(defn, supplied)
        sql = str(defn.build(params).compile(compile_kwargs={"literal_binds": True})).lower()
        assert "focus_costs" in sql
        assert sql.strip().startswith("select")


def test_run_query_carries_provenance() -> None:
    repo = RecordingRepo(rows=[{"billed_cost": 42}])
    result = run_query(repo, "total_spend", {"start": "2026-01-01", "end": "2026-02-01"})
    assert result.name == "total_spend"
    assert result.params["start"] == date(2026, 1, 1)
    assert result.rows == [{"billed_cost": 42}]
    assert repo.statement is not None
