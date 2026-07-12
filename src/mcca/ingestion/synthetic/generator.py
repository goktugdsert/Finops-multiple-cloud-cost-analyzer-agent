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

# A compute workload covered by a Savings Plan. Emitted as SavingsPlanCoveredUsage +
# SavingsPlanRecurringFee lines so those (previously mapped-but-never-emitted) FOCUS charge
# categories are actually exercised. Deterministic, no anomalies of its own.
_SP_SPEC = ServiceSpec(
    _EC2,
    "Hrs",
    Decimal("0.096"),
    base_units=300,
    growth_per_month=0.0,
    weekend_factor=1.0,
    noise=0.02,
    team="platform",
    environment="prod",
    owner="alice",
)

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
    # Savings Plan: a covered EC2 workload discounted `sp_discount` off on-demand, paid via a
    # flat daily recurring fee. Covered usage is billed $0 (its cost is the fee) and the fee
    # amortizes back onto the usage — the accurate AWS SP shape.
    savings_plan: bool = True
    sp_discount: float = 0.27
    # Enterprise/negotiated discount off the public list price (e.g. an EDP). The modeled
    # rates are the NEGOTIATED (contracted) rates you're billed, so ContractedCost == billed
    # for on-demand usage and the public ListCost sits above it: list = billed / (1 - edp).
    negotiated_discount: float = 0.10
    anomalies: tuple[tuple[int, str, float], ...] = field(default=DEFAULT_ANOMALIES)


def _money(value: Decimal) -> str:
    return str(value.quantize(_MONEY_Q, rounding=ROUND_HALF_UP))


def _metrics(
    unblended: Decimal,
    amortized: Decimal,
    usage: Decimal,
    unit: str,
    currency: str = "USD",
    *,
    list_cost: Decimal | None = None,
    contracted: Decimal | None = None,
    blended: Decimal | None = None,
) -> dict[str, dict[str, str]]:
    # Net* equals gross here: credits/refunds are modeled as their own lines, exactly as
    # Cost Explorer splits them out. The discount stack is list >= contracted >= billed:
    #   ListCost       — public on-demand price, before any negotiated discount.
    #   ContractedCost — price at the negotiated (contracted) rate, before commitment discounts.
    #   Unblended      — invoiced amount (after commitment discounts too).
    # BlendedCost is AWS's consolidated-average measure — differs for commitment-covered usage.
    list_cost = unblended if list_cost is None else list_cost
    contracted = unblended if contracted is None else contracted
    blended = unblended if blended is None else blended
    return {
        "UnblendedCost": {"Amount": _money(unblended), "Unit": currency},
        "NetUnblendedCost": {"Amount": _money(unblended), "Unit": currency},
        "BlendedCost": {"Amount": _money(blended), "Unit": currency},
        "NetBlendedCost": {"Amount": _money(blended), "Unit": currency},
        "AmortizedCost": {"Amount": _money(amortized), "Unit": currency},
        "NetAmortizedCost": {"Amount": _money(amortized), "Unit": currency},
        "ListCost": {"Amount": _money(list_cost), "Unit": currency},
        "ContractedCost": {"Amount": _money(contracted), "Unit": currency},
        "UsageQuantity": {"Amount": _money(usage), "Unit": unit},
    }


def _list_price(billed: Decimal, config: GeneratorConfig) -> Decimal:
    """Public list price implied by a negotiated (billed) amount: list = billed / (1 - edp)."""
    factor = Decimal(str(1 - config.negotiated_discount))
    return billed / factor if factor > 0 else billed


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


def _savings_plan_groups(
    day_index: int, day: date, config: GeneratorConfig
) -> list[dict[str, Any]]:
    """Emit the two line items an active Savings Plan produces on a given day.

    - SavingsPlanCoveredUsage: usage the plan covers. Billed (unblended) is $0 because the
      cost is paid via the recurring fee; ListCost shows the on-demand price it displaces,
      and AmortizedCost carries the plan cost allocated to this usage.
    - SavingsPlanRecurringFee: the flat committed charge (a Purchase); it is what's invoiced,
      and it amortizes into the covered usage above so amortized totals stay consistent.
    """
    usage = Decimal(str(_daily_usage(_SP_SPEC, day_index, day, config)))
    on_demand = _SP_SPEC.rate * usage  # negotiated on-demand cost this usage displaces
    amortized = on_demand * Decimal(str(1 - config.sp_discount))  # SP cost for this usage
    fee = amortized  # recurring fee equals the amortized covered cost (consistent totals)
    return [
        _group(
            [_SP_SPEC.key, "SavingsPlanCoveredUsage"],
            # Billed $0 (covered); contracted = negotiated on-demand, list = public price
            # above it, effective = amortized SP cost.
            _metrics(
                Decimal("0"),
                amortized,
                usage,
                _SP_SPEC.unit,
                list_cost=_list_price(on_demand, config),
                contracted=on_demand,
                blended=amortized,
            ),
            tags=_SP_SPEC.tags(),
        ),
        _group(
            [_SP_SPEC.key, "SavingsPlanRecurringFee"],
            # The invoiced fee; amortized $0 here (its cost is amortized into the usage).
            _metrics(fee, Decimal("0"), Decimal("0"), "N/A", list_cost=fee, blended=fee),
        ),
    ]


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
            # For RI-covered services the consolidated BlendedCost reflects the amortized
            # (post-commitment) figure, so blended != unblended — captured via x_blended_cost.
            blended = amortized if spec.ri_savings else unblended
            groups.append(
                _group(
                    [spec.key, "Usage"],
                    # On-demand: billed at the negotiated rate, so contracted == billed and
                    # the public list price sits above both.
                    _metrics(
                        unblended,
                        amortized,
                        usage,
                        spec.unit,
                        list_cost=_list_price(unblended, config),
                        contracted=unblended,
                        blended=blended,
                    ),
                    tags=spec.tags(),
                )
            )
            if spec.taxable:
                taxable_unblended += unblended

        if config.savings_plan:
            groups.extend(_savings_plan_groups(day_index, day, config))

        if config.ec2_daily_ri_fee:
            fee = config.ec2_daily_ri_fee
            # RIFee is a recurring Purchase; RI-covered EC2 usage above is billed on-demand
            # while this fee amortizes the reservation. (Real per-line RI amortization comes
            # from the Cost & Usage Report; validated exactly only against a real account.)
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
