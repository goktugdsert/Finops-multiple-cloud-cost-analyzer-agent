"""Synthetic Azure provider: Cost Management Query responses from real-ish Azure rates.

Reuses the same usage-modeling engine as the AWS generator (ServiceSpec + daily usage with
growth/seasonality/noise/anomalies) but emits the columnar Azure Cost Management shape and
Azure services. Deterministic given a seed. Lets us build the Azure pipeline end-to-end
with no Azure account.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from mcca.ingestion.synthetic.generator import (
    GeneratorConfig,
    ServiceSpec,
    _daily_usage,
)

# Approximate Azure retail (pay-as-you-go) rates, us-east. Base usage sized so a month
# lands around ~$6-7k. One deliberately flat, untagged line (Managed Disks) = waste.
AZURE_SERVICES: list[ServiceSpec] = [
    ServiceSpec(
        "Virtual Machines",
        "Hours",
        Decimal("0.096"),
        base_units=980,
        ri_savings=0.30,
        growth_per_month=0.04,
        weekend_factor=0.7,
        noise=0.06,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "Storage",
        "GB-Mo",
        Decimal("0.0184"),
        base_units=1600,
        growth_per_month=0.05,
        noise=0.03,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "Azure SQL Database",
        "Hours",
        Decimal("0.34"),
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
        "Azure App Service",
        "Hours",
        Decimal("0.075"),
        base_units=430,
        growth_per_month=0.04,
        weekend_factor=0.85,
        noise=0.06,
        team="web",
        environment="prod",
        owner="dave",
    ),
    ServiceSpec(
        "Bandwidth",
        "GB",
        Decimal("0.087"),
        base_units=130,
        growth_per_month=0.04,
        weekend_factor=0.75,
        noise=0.10,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    ServiceSpec(
        "Azure Cosmos DB",
        "Hours",
        Decimal("0.008"),
        base_units=5200,
        growth_per_month=0.05,
        weekend_factor=0.85,
        noise=0.07,
        team="data",
        environment="prod",
        owner="bob",
    ),
    ServiceSpec(
        "Azure Monitor",
        "GB",
        Decimal("2.30"),
        base_units=7,
        growth_per_month=0.03,
        noise=0.05,
        team="platform",
        environment="prod",
        owner="alice",
    ),
    # Flat, untagged = unattached managed disks left running: structural waste.
    ServiceSpec(
        "Azure Managed Disks",
        "GB-Mo",
        Decimal("0.12"),
        base_units=45,
        steady_waste=True,
        noise=0.01,
    ),
]

_VM = "Virtual Machines"

# (day_index, service, multiplier) spikes injected into Azure usage.
AZURE_ANOMALIES: tuple[tuple[int, str, float], ...] = (
    (40, _VM, 3.0),  # scale-out event
    (100, "Bandwidth", 5.0),  # egress surge
    (160, "Azure SQL Database", 2.5),  # runaway query load
)

# Monthly reservation purchase (ChargeType Purchase), tagged to the platform team.
AZURE_MONTHLY_RESERVATION = Decimal("200.00")
# Monthly refund/credit (ChargeType Refund -> FOCUS Credit; negative) and the cost of
# reservation hours that went unused (ChargeType UnusedReservation -> FOCUS Adjustment).
# These exercise Azure's credit/adjustment charge types, previously mapped but never emitted.
AZURE_MONTHLY_REFUND = Decimal("-120.00")
AZURE_MONTHLY_UNUSED_RESERVATION = Decimal("35.00")

_COLUMNS: list[dict[str, str]] = [
    {"name": "Cost", "type": "Number"},
    {"name": "AmortizedCost", "type": "Number"},
    {"name": "UsageDate", "type": "Number"},
    {"name": "ServiceName", "type": "String"},
    {"name": "ResourceGroupName", "type": "String"},
    {"name": "ChargeType", "type": "String"},
    {"name": "Currency", "type": "String"},
    {"name": "Quantity", "type": "Number"},
    {"name": "UnitOfMeasure", "type": "String"},
    {"name": "team", "type": "String"},
    {"name": "environment", "type": "String"},
    {"name": "owner", "type": "String"},
]


def _rg(spec: ServiceSpec) -> str:
    return f"{spec.team or 'shared'}-rg"


def _row(
    cost: Decimal,
    amortized: Decimal,
    day: date,
    service: str,
    rg: str,
    charge: str,
    quantity: Decimal,
    unit: str,
    tags: dict[str, str],
) -> list[Any]:
    return [
        float(cost),
        float(amortized),
        int(day.strftime("%Y%m%d")),
        service,
        rg,
        charge,
        "USD",
        float(quantity),
        unit,
        tags.get("team", ""),
        tags.get("environment", ""),
        tags.get("owner", ""),
    ]


def build_azure_response(
    start: date, end: date, config: GeneratorConfig | None = None
) -> dict[str, Any]:
    """Build an Azure Cost Management Query response for [start, end) (end exclusive)."""
    # Azure services need Azure-specific anomaly keys; keep the caller's seed.
    config = replace(config or GeneratorConfig(), anomalies=AZURE_ANOMALIES)
    rows: list[list[Any]] = []

    for day_index in range((end - start).days):
        day = start + timedelta(days=day_index)
        for spec in AZURE_SERVICES:
            usage = Decimal(str(_daily_usage(spec, day_index, day, config)))
            cost = spec.rate * usage
            amortized = cost * Decimal(str(1 - spec.ri_savings))
            rows.append(
                _row(
                    cost,
                    amortized,
                    day,
                    spec.key,
                    _rg(spec),
                    "Usage",
                    usage,
                    spec.unit,
                    spec.tags(),
                )
            )
        if day.day == 1:
            platform_tags = {"team": "platform", "environment": "prod", "owner": "alice"}
            if AZURE_MONTHLY_RESERVATION:
                fee = AZURE_MONTHLY_RESERVATION
                rows.append(
                    _row(
                        fee,
                        fee,
                        day,
                        _VM,
                        "platform-rg",
                        "Purchase",
                        Decimal("0"),
                        "1 Month",
                        platform_tags,
                    )
                )
            if AZURE_MONTHLY_REFUND:
                refund = AZURE_MONTHLY_REFUND
                rows.append(
                    _row(
                        refund,
                        refund,
                        day,
                        _VM,
                        "platform-rg",
                        "Refund",
                        Decimal("0"),
                        "1 Month",
                        platform_tags,
                    )
                )
            if AZURE_MONTHLY_UNUSED_RESERVATION:
                unused = AZURE_MONTHLY_UNUSED_RESERVATION
                rows.append(
                    _row(
                        unused,
                        unused,
                        day,
                        "Azure Reservations",
                        "platform-rg",
                        "UnusedReservation",
                        Decimal("0"),
                        "1 Month",
                        platform_tags,
                    )
                )

    return {"properties": {"columns": _COLUMNS, "rows": rows}}


class SyntheticAzureClient:
    """Drop-in stand-in for an Azure Cost Management query client."""

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        self._config = config

    def query(self, start: date, end: date) -> dict[str, Any]:
        return build_azure_response(start, end, self._config)
