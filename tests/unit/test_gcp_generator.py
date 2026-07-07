"""The synthetic GCP provider is deterministic and flows through the real normalizer."""

from __future__ import annotations

from datetime import date

import pytest

from mcca.ingestion.gcp.billing_export import flatten_billing_rows
from mcca.ingestion.gcp.normalize import normalize_records
from mcca.ingestion.synthetic.gcp import GCP_SERVICES, build_gcp_rows
from mcca.ingestion.synthetic.generator import GeneratorConfig

START = date(2026, 1, 1)
END = date(2026, 7, 1)


def test_is_deterministic() -> None:
    assert build_gcp_rows(START, END, GeneratorConfig(seed=7)) == build_gcp_rows(
        START, END, GeneratorConfig(seed=7)
    )


def test_regular_cost_equals_usage_times_rate() -> None:
    rows = build_gcp_rows(START, START.replace(day=2))
    rates = {s.key: s.rate for s in GCP_SERVICES}
    for row in rows:
        if row["cost_type"] != "regular":
            continue
        qty = float(row["usage"]["amount"])
        expected = float(rates[row["service"]["description"]]) * qty
        assert float(row["cost"]) == pytest.approx(expected, rel=1e-6)


def test_committed_use_discount_and_tax_present() -> None:
    rows = build_gcp_rows(START, END)
    assert any(r["cost_type"] == "tax" for r in rows)
    gce = [r for r in rows if r["service"]["description"] == "Compute Engine"]
    assert gce and gce[0]["credits"] and gce[0]["credits"][0]["amount"] < 0


def test_flows_through_normalizer_with_credits_netted() -> None:
    records = normalize_records(flatten_billing_rows(build_gcp_rows(START, END)))
    assert len(records) > 1000
    assert all(r.provider_name == "GCP" for r in records)
    # Compute Engine has a CUD credit -> billed (net) below list (gross).
    gce = next(r for r in records if r.service_name == "Compute Engine")
    assert gce.billed_cost < gce.list_cost
