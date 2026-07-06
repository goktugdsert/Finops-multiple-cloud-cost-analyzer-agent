"""The synthetic generator produces realistic, deterministic AWS-shaped cost data.

Verifies cost == usage x rate, RI amortization, the charge types a real bill carries,
deterministic anomalies, and that it all flows cleanly through the real normalizer.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from mcca.ingestion.aws.cost_explorer import flatten_response
from mcca.ingestion.aws.normalize import normalize_records
from mcca.ingestion.synthetic.generator import (
    SERVICES,
    GeneratorConfig,
    build_response,
)

START = date(2026, 1, 1)
END = date(2026, 7, 1)  # 181 days: covers all default anomaly indices (38/95/150)


def _usage_groups(bucket: dict) -> dict[str, dict]:
    """Map service name -> group dict for RECORD_TYPE == 'Usage' in a day bucket."""
    return {g["Keys"][0]: g for g in bucket["Groups"] if g["Keys"][1] == "Usage"}


def test_is_deterministic_for_a_seed() -> None:
    a = build_response(START, END, GeneratorConfig(seed=7))
    b = build_response(START, END, GeneratorConfig(seed=7))
    assert a == b


def test_cost_equals_usage_times_rate() -> None:
    day0 = build_response(START, START.replace(day=2))["ResultsByTime"][0]
    groups = _usage_groups(day0)
    rates = {s.key: s.rate for s in SERVICES}
    for key, group in groups.items():
        usage = Decimal(group["Metrics"]["UsageQuantity"]["Amount"])
        unblended = Decimal(group["Metrics"]["UnblendedCost"]["Amount"])
        expected = (rates[key] * usage).quantize(Decimal("0.0000000001"))
        assert unblended == expected, key


def test_amortization_reflects_ri_savings() -> None:
    day0 = build_response(START, START.replace(day=2))["ResultsByTime"][0]
    groups = _usage_groups(day0)
    ec2 = groups["Amazon Elastic Compute Cloud - Compute"]  # ri_savings = 0.28
    unblended = Decimal(ec2["Metrics"]["UnblendedCost"]["Amount"])
    amortized = Decimal(ec2["Metrics"]["AmortizedCost"]["Amount"])
    assert amortized < unblended
    assert amortized == (unblended * Decimal("0.72")).quantize(Decimal("0.0000000001"))

    s3 = groups["Amazon Simple Storage Service"]  # no RI coverage
    assert s3["Metrics"]["AmortizedCost"]["Amount"] == s3["Metrics"]["UnblendedCost"]["Amount"]


def test_bill_carries_all_charge_types() -> None:
    resp = build_response(START, END)
    record_types = {g["Keys"][1] for b in resp["ResultsByTime"] for g in b["Groups"]}
    assert {"Usage", "RIFee", "Tax", "Credit"} <= record_types


def test_tax_is_rate_times_taxable_usage() -> None:
    cfg = GeneratorConfig(tax_rate=0.07)
    day0 = build_response(START, START.replace(day=2), cfg)["ResultsByTime"][0]
    taxable = sum(
        Decimal(g["Metrics"]["UnblendedCost"]["Amount"])
        for g in day0["Groups"]
        if g["Keys"][1] == "Usage"
    )
    tax_line = next(g for g in day0["Groups"] if g["Keys"][1] == "Tax")
    tax = Decimal(tax_line["Metrics"]["UnblendedCost"]["Amount"])
    assert tax == (taxable * Decimal("0.07")).quantize(Decimal("0.0000000001"))


def test_anomaly_multiplies_exactly() -> None:
    # Same seed => identical baseline usage; the only difference is the injected spike,
    # so the ratio on the anomaly day equals the multiplier.
    key = "Amazon Elastic Compute Cloud - Compute"
    with_spike = build_response(START, END, GeneratorConfig(seed=3, anomalies=((38, key, 2.5),)))
    without = build_response(START, END, GeneratorConfig(seed=3, anomalies=()))
    spiked = Decimal(
        _usage_groups(with_spike["ResultsByTime"][38])[key]["Metrics"]["UsageQuantity"]["Amount"]
    )
    base = Decimal(
        _usage_groups(without["ResultsByTime"][38])[key]["Metrics"]["UsageQuantity"]["Amount"]
    )
    assert spiked / base == pytest.approx(2.5, abs=1e-6)


def test_flows_through_normalizer_to_focus_records() -> None:
    resp = build_response(START, END)
    records = normalize_records(flatten_response([resp]))
    assert len(records) > 1000  # ~8 services x 181 days + tax/fee/credit lines
    # Headline spend is positive; credits show up as negatives.
    assert sum(r.billed_cost for r in records) > 0
    assert any(r.charge_category == "Credit" and r.billed_cost < 0 for r in records)
    # Every service we model appears.
    seen = {r.service_name for r in records}
    assert {s.key for s in SERVICES} <= seen
