"""Read-only Azure Cost Management client factory.

Builds an Azure Cost Management client from Settings using azure-identity (a least-
privilege reader credential). READ-ONLY: only query APIs are ever called. Stub for now —
the synthetic provider (mcca.ingestion.synthetic.azure) exercises the same code path, and
real Azure wiring lands when an account is available.
"""

from __future__ import annotations

from typing import Any

from mcca.config import Settings, get_settings


def cost_management_client(settings: Settings | None = None) -> Any:
    """Return a read-only Azure Cost Management query client."""
    _ = settings or get_settings()
    raise NotImplementedError(
        "Real Azure Cost Management wiring needs azure-identity + "
        "azure-mgmt-costmanagement; use the synthetic provider for now."
    )
