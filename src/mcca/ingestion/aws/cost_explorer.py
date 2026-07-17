"""Pull raw cost/usage data from AWS Cost Explorer (read-only).

`fetch_cost_and_usage` handles pagination and returns a flat list of `RawCostRow`s — a
stable, provider-shaped intermediate that `normalize.py` maps to FOCUS. The flattening is
a pure function (`flatten_response`) so it can be unit-tested without AWS.

Design notes (v1):
- Granularity DAILY, grouped by SERVICE + RECORD_TYPE. Cost Explorer allows only two
  group-by dimensions; RECORD_TYPE is kept because it drives the FOCUS charge category
  (Usage / Tax / Credit / Refund / RIFee / ...), which is load-bearing for "a dollar
  means the same thing". Account/region/resource-level and tag-based attribution need
  the Cost & Usage Report (CUR) and are deferred.
- Metrics requested cover blended vs unblended and amortization so normalization can pick
  the correct FOCUS cost measures (see normalize.py). Numbers must be validated against
  the Cost Explorer console before being trusted (ARCHITECTURE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from mcca.ingestion.aws.client import cost_explorer_client

# Cost measures + usage. NetUnblendedCost / NetAmortizedCost are post-credit.
DEFAULT_METRICS: list[str] = [
    "UnblendedCost",
    "NetUnblendedCost",
    "AmortizedCost",
    "NetAmortizedCost",
    "UsageQuantity",
]

DEFAULT_GROUP_BY: list[dict[str, str]] = [
    {"Type": "DIMENSION", "Key": "SERVICE"},
    {"Type": "DIMENSION", "Key": "RECORD_TYPE"},
]


@dataclass(frozen=True)
class RawCostRow:
    """One flattened Cost Explorer result: a time bucket + group + its metrics."""

    start: str  # inclusive, "YYYY-MM-DD"
    end: str  # exclusive, "YYYY-MM-DD"
    groups: dict[str, str]  # e.g. {"SERVICE": "Amazon EC2", "RECORD_TYPE": "Usage"}
    metrics: dict[str, dict[str, str]]  # e.g. {"NetUnblendedCost": {"Amount","Unit"}}
    estimated: bool
    tags: dict[str, str] = field(default_factory=dict)  # cost-allocation tags on the line


def flatten_response(
    pages: list[dict[str, Any]], group_by: list[dict[str, str]] | None = None
) -> list[RawCostRow]:
    """Flatten paginated GetCostAndUsage responses into RawCostRows (pure function)."""
    group_by = group_by if group_by is not None else DEFAULT_GROUP_BY
    keys = [g["Key"] for g in group_by]
    rows: list[RawCostRow] = []
    for page in pages:
        for bucket in page.get("ResultsByTime", []):
            period = bucket["TimePeriod"]
            estimated = bool(bucket.get("Estimated", False))
            groups = bucket.get("Groups", [])
            if groups:
                for grp in groups:
                    labeled = dict(zip(keys, grp.get("Keys", []), strict=False))
                    rows.append(
                        RawCostRow(
                            start=period["Start"],
                            end=period["End"],
                            groups=labeled,
                            metrics=grp.get("Metrics", {}),
                            estimated=estimated,
                            tags=grp.get("Tags", {}),
                        )
                    )
            else:
                # Ungrouped: the bucket Total carries the metrics.
                rows.append(
                    RawCostRow(
                        start=period["Start"],
                        end=period["End"],
                        groups={},
                        metrics=bucket.get("Total", {}),
                        estimated=estimated,
                    )
                )
    return rows


def fetch_cost_and_usage(
    start: date,
    end: date,
    *,
    client: Any | None = None,
    granularity: str = "DAILY",
    metrics: list[str] | None = None,
    group_by: list[dict[str, str]] | None = None,
    cost_filter: dict[str, Any] | None = None,
) -> list[RawCostRow]:
    """Fetch raw Cost Explorer rows for [start, end) (end exclusive), following pages."""
    client = client or cost_explorer_client()
    metrics = metrics or DEFAULT_METRICS
    group_by = group_by if group_by is not None else DEFAULT_GROUP_BY

    pages: list[dict[str, Any]] = []
    next_token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
            "Granularity": granularity,
            "Metrics": metrics,
            "GroupBy": group_by,
        }
        if cost_filter:
            kwargs["Filter"] = cost_filter
        if next_token:
            kwargs["NextPageToken"] = next_token
        response = client.get_cost_and_usage(**kwargs)
        pages.append(response)
        next_token = response.get("NextPageToken")
        if not next_token:
            break
    return flatten_response(pages, group_by)
