"""Generate Cost Explorer-shaped responses from realistic AWS rates x modeled usage.

The cost of every line is derived the way AWS composes a bill:

    unblended_cost = usage_quantity x on_demand_rate      (as invoiced, on-demand)
    amortized_cost = unblended_cost x (1 - ri_savings)    (RI/SP spread in)

On top of usage lines we add the charge types a real bill carries: a recurring RI fee
(Purchase), daily tax (Tax), and a monthly promotional credit (Credit, negative). Usage
follows a baseline + monthly growth + weekday/weekend seasonality + seeded noise, with a
few injected spikes and one deliberately flat "steady structural waste" line.

Everything is deterministic given a seed, so tests and demos are reproducible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Money is emitted as 10-dp strings, matching Cost Explorer's string amounts and the
# warehouse NUMERIC(20,10) columns.
_MONEY_Q = Decimal("0.0000000001")


@dataclass(frozen=True)
class ServiceSpec:
    """One AWS service: its billing unit, real on-demand rate, and usage behaviour."""

    key: str  # SERVICE dimension value, exactly as Cost Explorer reports it
    unit: str  # UsageQuantity unit (Hrs, GB-Mo, GB, Lambda-GB-Second, ...)
    rate: Decimal  # USD per unit (us-east-1 on-demand, approx public price)
    base_units: float  # mean daily usage quantity
    ri_savings: float = 0.0  # amortized = unblended x (1 - ri_savings)
    growth_per_month: float = 0.03  # compounding monthly growth
    weekend_factor: float = 1.0  # multiplier applied on Sat/Sun
    noise: float = 0.05  # relative gaussian jitter (std dev)
    taxable: bool = True
    steady_waste: bool = False  # flat: no growth/seasonality (structural waste)
    # Cost-allocation tags emitted on usage lines (drive attribution). None = untagged.
    team: str | None = None
    environment: str | None = None
    owner: str | None = None

    def tags(self) -> dict[str, str]:
        pairs = {"team": self.team, "environment": self.environment, "owner": self.owner}
        return {k: v for k, v in pairs.items() if v}


# Approximate AWS us-east-1 on-demand prices. Base usage is sized so a typical month
# lands around ~$7-8k of usage — believable mid-startup scale.
SERVICES: list[ServiceSpec] = [
    ServiceSpec(
        "Amazon Elastic Compute Cloud - Compute",
        "Hrs",
        Decimal("0.096"),  # ~m5.large blended
        base_units=1385,
        ri_savings=0.28,
        growth_per_month=0.04,
        weekend_factor=0.65,
        noise=0.06,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "Amazon Simple Storage Service",
        "GB-Mo",
        Decimal("0.023"),
        base_units=723,
        growth_per_month=0.05,
        noise=0.03,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "Amazon Relational Database Service",
        "Hrs",
        Decimal("0.145"),  # ~db.m5.large
        base_units=345,
        ri_savings=0.30,
        growth_per_month=0.03,
        weekend_factor=0.9,
        noise=0.05,
        team="data",
        environment="prod",
        owner="bob",
    ),
    ServiceSpec(
        "AWS Lambda",
        "Lambda-GB-Second",
        Decimal("0.0000166667"),
        base_units=600000,
        growth_per_month=0.06,
        weekend_factor=0.7,
        noise=0.08,
        team="data",
        environment="staging",
        owner="carol",
    ),
    ServiceSpec(
        "AWS Data Transfer",
        "GB",
        Decimal("0.09"),
        base_units=148,
        growth_per_month=0.04,
        weekend_factor=0.75,
        noise=0.10,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "AmazonCloudWatch",
        "Metrics",
        Decimal("0.10"),
        base_units=50,
        growth_per_month=0.03,
        noise=0.05,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "Amazon DynamoDB",
        "ReadRequestUnits",
        Decimal("0.00013"),
        base_units=64000,
        growth_per_month=0.05,
        weekend_factor=0.8,
        noise=0.07,
        team="data",
        environment="prod",
        owner="bob",
    ),
    # Deliberately flat = unattached EBS volumes left running: steady structural waste.
    ServiceSpec(
        "Amazon Elastic Block Store",
        "GB-Mo",
        Decimal("0.10"),
        base_units=40,
        steady_waste=True,
        noise=0.01,
    ),
]

_EC2 = "Amazon Elastic Compute Cloud - Compute"

# (day_index, service_key, multiplier) spikes injected into usage.
DEFAULT_ANOMALIES: tuple[tuple[int, str, float], ...] = (
    (38, _EC2, 2.5),  # runaway autoscaling
    (95, "AWS Data Transfer", 6.0),  # egress surge / misconfig
    (150, "AWS Lambda", 4.0),  # hot loop / retry storm
)


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = 42
    tax_rate: float = 0.07
    monthly_credit: Decimal = Decimal("250.00")
    ec2_daily_ri_fee: Decimal = Decimal("18.00")
    anomalies: tuple[tuple[int, str, float], ...] = field(default=DEFAULT_ANOMALIES)


def _money(value: Decimal) -> str:
    return str(value.quantize(_MONEY_Q, rounding=ROUND_HALF_UP))


def _metrics(
    unblended: Decimal, amortized: Decimal, usage: Decimal, unit: str, currency: str = "USD"
) -> dict[str, dict[str, str]]:
    # Net* equals gross here: credits/refunds are modeled as their own lines, exactly as
    # Cost Explorer splits them out.
    return {
        "UnblendedCost": {"Amount": _money(unblended), "Unit": currency},
        "NetUnblendedCost": {"Amount": _money(unblended), "Unit": currency},
        "AmortizedCost": {"Amount": _money(amortized), "Unit": currency},
        "NetAmortizedCost": {"Amount": _money(amortized), "Unit": currency},
        "UsageQuantity": {"Amount": _money(usage), "Unit": unit},
    }


def _group(
    keys: list[str], metrics: dict[str, dict[str, str]], tags: dict[str, str] | None = None
) -> dict[str, Any]:
    group: dict[str, Any] = {"Keys": keys, "Metrics": metrics}
    if tags:
        group["Tags"] = tags
    return group


def _daily_usage(spec: ServiceSpec, day_index: int, day: date, config: GeneratorConfig) -> float:
    """Modeled usage quantity for a service on a given day (deterministic per seed)."""
    # Seeded per (seed, service, day) so noise is stable regardless of iteration order
    # and independent of whether anomalies are configured.
    rng = random.Random(f"{config.seed}:{spec.key}:{day.isoformat()}")

    if spec.steady_waste:
        factor = 1.0
    else:
        growth = (1 + spec.growth_per_month) ** (day_index / 30.0)
        weekend = spec.weekend_factor if day.weekday() >= 5 else 1.0
        factor = growth * weekend

    noise = 1 + rng.gauss(0, spec.noise)
    noise = max(0.5, min(1.5, noise))
    usage = spec.base_units * factor * noise

    for idx, key, mult in config.anomalies:
        if idx == day_index and key == spec.key:
            usage *= mult

    return max(0.0, usage)


def build_response(start: date, end: date, config: GeneratorConfig | None = None) -> dict[str, Any]:
    """Build a Cost Explorer GetCostAndUsage response for [start, end) (end exclusive)."""
    config = config or GeneratorConfig()
    buckets: list[dict[str, Any]] = []

    for day_index in range((end - start).days):
        day = start + timedelta(days=day_index)
        groups: list[dict[str, Any]] = []
        taxable_unblended = Decimal("0")

        for spec in SERVICES:
            usage = Decimal(str(_daily_usage(spec, day_index, day, config)))
            unblended = spec.rate * usage
            amortized = unblended * Decimal(str(1 - spec.ri_savings))
            groups.append(
                _group(
                    [spec.key, "Usage"],
                    _metrics(unblended, amortized, usage, spec.unit),
                    tags=spec.tags(),
                )
            )
            if spec.taxable:
                taxable_unblended += unblended

        if config.ec2_daily_ri_fee:
            fee = config.ec2_daily_ri_fee
            groups.append(_group([_EC2, "RIFee"], _metrics(fee, fee, Decimal("0"), "N/A")))

        if config.tax_rate:
            tax = taxable_unblended * Decimal(str(config.tax_rate))
            groups.append(_group(["Tax", "Tax"], _metrics(tax, tax, Decimal("0"), "N/A")))

        if day.day == 1 and config.monthly_credit:
            credit = -config.monthly_credit
            groups.append(_group([_EC2, "Credit"], _metrics(credit, credit, Decimal("0"), "N/A")))

        buckets.append(
            {
                "TimePeriod": {
                    "Start": day.isoformat(),
                    "End": (day + timedelta(days=1)).isoformat(),
                },
                "Total": {},
                "Groups": groups,
                "Estimated": False,
            }
        )

    return {
        "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
        "ResultsByTime": buckets,
        "DimensionValueAttributes": [],
    }
