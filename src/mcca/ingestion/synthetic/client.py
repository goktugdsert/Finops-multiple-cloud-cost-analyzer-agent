"""A drop-in stand-in for the boto3 Cost Explorer client, backed by the generator.

Because it exposes `get_cost_and_usage(**kwargs)` with the same contract, it plugs into
`fetch_cost_and_usage(..., client=...)` and `ingest_cost_and_usage(..., client=...)`
unchanged — synthetic data travels the exact same code path as real AWS data.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mcca.ingestion.synthetic.generator import GeneratorConfig, build_response


class SyntheticCostExplorerClient:
    """Returns generated GetCostAndUsage responses honoring the requested TimePeriod.

    Grouping is always SERVICE + RECORD_TYPE (what our ingestion requests); the GroupBy
    kwarg is accepted and ignored, as the generator fixes that shape.
    """

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        self.config = config or GeneratorConfig()

    def get_cost_and_usage(self, **kwargs: Any) -> dict[str, Any]:
        period = kwargs["TimePeriod"]
        start = date.fromisoformat(period["Start"])
        end = date.fromisoformat(period["End"])
        response = build_response(start, end, self.config)
        response["NextPageToken"] = None
        return response
