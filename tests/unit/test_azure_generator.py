"""The synthetic Azure provider is deterministic and flows through the real normalizer."""

from __future__ import annotations

from datetime import date

import pytest

from mcca.ingestion.azure.cost_management import flatten_query_response
from mcca.ingestion.azure.normalize import normalize_records
from mcca.ingestion.synthetic.azure import AZURE_SERVICES, build_azure_response
from mcca.ingestion.synthetic.generator import GeneratorConfig

START = date(2026, 1, 1)
END = date(2026, 7, 1)


def _cols(resp):
    return [c["name"] for c in resp["properties"]["columns"]]


def test_is_deterministic() -> None:
    a = build_azure_response(START, END, GeneratorConfig(seed=7))
    b = build_azure_response(START, END, GeneratorConfig(seed=7))
    assert a == b


def test_cost_equals_usage_times_rate() -> None:
    resp = build_azure_response(START, START.replace(day=2))
    cols = _cols(resp)
    ci = {n: i for i, n in enumerate(cols)}
    rates = {s.key: s.rate for s in AZURE_SERVICES}
    for row in resp["properties"]["rows"]:
        if row[ci["ChargeType"]] != "Usage":
            continue
        qty = float(row[ci["Quantity"]])
        cost = float(row[ci["Cost"]])
        expected = float(rates[row[ci["ServiceName"]]]) * qty
        assert cost == pytest.approx(expected, rel=1e-6)


def test_has_purchase_line_and_untagged_waste() -> None:
    resp = build_azure_response(START, END)
    charge_types = {r[_cols(resp).index("ChargeType")] for r in resp["properties"]["rows"]}
    assert {"Usage", "Purchase"} <= charge_types
    # Managed Disks is emitted untagged (empty tag columns).
    ci = {n: i for i, n in enumerate(_cols(resp))}
    disks = [r for r in resp["properties"]["rows"] if r[ci["ServiceName"]] == "Azure Managed Disks"]
    assert disks and disks[0][ci["team"]] == ""


def test_flows_through_normalizer() -> None:
    records = normalize_records(flatten_query_response(build_azure_response(START, END)))
    assert len(records) > 1000
    assert all(r.provider_name == "Azure" for r in records)
    assert sum(r.billed_cost for r in records) > 0
    seen = {r.service_name for r in records}
    assert {s.key for s in AZURE_SERVICES} <= seen
