"""Write normalized FOCUS records into the warehouse via the repository interface.

Depends only on `WarehouseRepository` — not on Postgres directly. Stub this session.
"""

from __future__ import annotations

from collections.abc import Sequence

from mcca.warehouse.models import FocusRecord
from mcca.warehouse.repository import WarehouseRepository


def load_records(repo: WarehouseRepository, records: Sequence[FocusRecord]) -> int:
    """Persist normalized records through the warehouse repository."""
    raise NotImplementedError("Loader orchestration lands in build step 2.")
