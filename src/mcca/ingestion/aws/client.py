"""Read-only boto3 client factory for AWS billing/usage services.

Builds boto3 clients (Cost Explorer, CloudWatch, and S3 for CUR) from Settings, using a
named profile or explicit credentials. READ-ONLY: callers must only ever invoke read
APIs; the agent never mutates or terminates infrastructure.

Stub this session — wired up in build step 2.
"""

from __future__ import annotations

from typing import Any

from mcca.config import Settings


def build_session(settings: Settings | None = None) -> Any:
    """Return a boto3 Session configured for least-privilege, read-only access."""
    raise NotImplementedError("AWS session wiring lands in build step 2.")


def cost_explorer_client(settings: Settings | None = None) -> Any:
    """Return a read-only Cost Explorer client."""
    raise NotImplementedError("Cost Explorer client lands in build step 2.")
