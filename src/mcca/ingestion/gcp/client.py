"""Read-only BigQuery client factory for the GCP billing export.

Builds a BigQuery client (google-cloud-bigquery + a least-privilege reader service
account) to query the standard billing export table. READ-ONLY. Stub for now — the
synthetic provider exercises the same path; real wiring lands when a project is available.
"""

from __future__ import annotations

from typing import Any

from mcca.config import Settings, get_settings


def bigquery_client(settings: Settings | None = None) -> Any:
    """Return a read-only BigQuery client for the billing export."""
    _ = settings or get_settings()
    raise NotImplementedError(
        "Real GCP wiring needs google-cloud-bigquery + a billing-export table; "
        "use the synthetic provider for now."
    )
