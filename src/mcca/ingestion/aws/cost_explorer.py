"""Pull raw cost/usage data from AWS Cost Explorer (read-only).

Stub this session. Build step 2 implements paginated GetCostAndUsage pulls and returns
the raw AWS payloads for normalization. Numbers pulled here are validated against the
Cost Explorer console until they match exactly.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def fetch_cost_and_usage(start: date, end: date) -> list[dict[str, Any]]:
    """Fetch raw Cost Explorer records for [start, end)."""
    raise NotImplementedError("Cost Explorer ingestion lands in build step 2.")
