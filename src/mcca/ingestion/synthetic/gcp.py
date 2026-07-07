"""Synthetic GCP provider: BigQuery billing-export rows from real-ish GCP rates.

Same usage-modeling engine as AWS/Azure, emitting the nested BigQuery billing-export shape
(service, sku, project, labels[], credits[], cost_type, usage). Committed-use discounts are
modeled as credits inside each row, exactly as GCP reports them. Deterministic per seed.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from mcca.ingestion.synthetic.generator import GeneratorConfig, ServiceSpec, _daily_usage

# Approximate GCP list rates, us-central1. One flat, untagged line (Persistent Disk) = waste.
GCP_SERVICES: list[ServiceSpec] = [
    ServiceSpec(
        "Compute Engine",
        "hour",
        Decimal("0.0475"),
        base_units=1200,
        ri_savings=0.30,
        growth_per_month=0.04,
        weekend_factor=0.7,
        noise=0.06,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "Cloud Storage",
        "gibibyte month",
        Decimal("0.020"),
        base_units=1400,
        growth_per_month=0.05,
        noise=0.03,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "BigQuery",
        "gibibyte",
        Decimal("0.005"),
        base_units=9000,
        growth_per_month=0.06,
        weekend_factor=0.8,
        noise=0.08,
        team="data",
        environment="prod",
        owner="bob",
    ),
    ServiceSpec(
        "Cloud SQL",
        "hour",
        Decimal("0.10"),
        base_units=210,
        ri_savings=0.25,
        growth_per_month=0.03,
        weekend_factor=0.9,
        noise=0.05,
        team="data",
        environment="prod",
        owner="bob",
    ),
    ServiceSpec(
        "Cloud Run",
        "hour",
        Decimal("0.024"),
        base_units=520,
        growth_per_month=0.05,
        weekend_factor=0.8,
        noise=0.07,
        team="web",
        environment="prod",
        owner="dave",
    ),
    ServiceSpec(
        "Networking",
        "gibibyte",
        Decimal("0.12"),
        base_units=110,
        growth_per_month=0.04,
        weekend_factor=0.75,
        noise=0.10,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "Cloud Logging",
        "gibibyte",
        Decimal("0.50"),
        base_units=14,
        growth_per_month=0.03,
        noise=0.05,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    # Flat, untagged = orphaned persistent disks: structural waste.
    ServiceSpec(
        "Compute Engine Persistent Disk",
        "gibibyte month",
        Decimal("0.10"),
        base_units=42,
        steady_waste=True,
        noise=0.01,
    ),
]

_GCE = "Compute Engine"

GCP_ANOMALIES: tuple[tuple[int, str, float], ...] = (
    (45, _GCE, 3.0),  # scale-out
    (105, "Networking", 5.0),  # egress surge
    (165, "BigQuery", 4.0),  # runaway query scan
)

GCP_TAX_RATE = 0.05

_PROJECTS: dict[str, tuple[str, str]] = {
    "platform": ("platform-prod", "Platform Production"),
    "data": ("data-analytics", "Data Analytics"),
    "web": ("web-prod", "Web Production"),
}


def _project(spec: ServiceSpec) -> tuple[str, str]:
    return _PROJECTS.get(spec.team or "", ("shared-svc", "Shared Services"))


def _usage_row(spec: ServiceSpec, day: date, usage: Decimal) -> dict[str, Any]:
    gross = spec.rate * usage
    project_id, project_name = _project(spec)
    credits = []
    if spec.ri_savings:
        credits.append(
            {
                "name": "Committed use discount",
                "amount": float(-(gross * Decimal(str(spec.ri_savings)))),
            }
        )
    return {
        "service": {"description": spec.key},
        "sku": {"description": f"{spec.key} usage"},
        "usage_start_time": f"{day.isoformat()}T00:00:00Z",
        "project": {"id": project_id, "name": project_name},
        "labels": [{"key": k, "value": v} for k, v in spec.tags().items()],
        "cost": float(gross),
        "currency": "USD",
        "cost_type": "regular",
        "usage": {"amount": float(usage), "unit": spec.unit},
        "credits": credits,
        "location": {"region": "us-central1"},
    }


def build_gcp_rows(
    start: date, end: date, config: GeneratorConfig | None = None
) -> list[dict[str, Any]]:
    """Build GCP BigQuery billing-export rows for [start, end) (end exclusive)."""
    config = replace(config or GeneratorConfig(), anomalies=GCP_ANOMALIES)
    rows: list[dict[str, Any]] = []

    for day_index in range((end - start).days):
        day = start + timedelta(days=day_index)
        daily_net = Decimal("0")
        for spec in GCP_SERVICES:
            usage = Decimal(str(_daily_usage(spec, day_index, day, config)))
            gross = spec.rate * usage
            daily_net += gross * Decimal(str(1 - spec.ri_savings))
            rows.append(_usage_row(spec, day, usage))
        if GCP_TAX_RATE:
            tax = daily_net * Decimal(str(GCP_TAX_RATE))
            rows.append(
                {
                    "service": {"description": "Tax"},
                    "sku": {"description": "Sales tax"},
                    "usage_start_time": f"{day.isoformat()}T00:00:00Z",
                    "project": {"id": "billing", "name": "Billing"},
                    "labels": [],
                    "cost": float(tax),
                    "currency": "USD",
                    "cost_type": "tax",
                    "usage": {},
                    "credits": [],
                    "location": {"region": "us-central1"},
                }
            )
    return rows


class SyntheticBigQueryClient:
    """Drop-in stand-in for a BigQuery billing-export query client."""

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        self._config = config

    def query(self, start: date, end: date) -> list[dict[str, Any]]:
        return build_gcp_rows(start, end, self._config)
