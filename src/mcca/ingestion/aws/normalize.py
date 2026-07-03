"""Normalize raw AWS cost data into FOCUS `FocusRecord`s.

This is where cross-cloud correctness is earned: handle RIs, Savings Plans, credits,
amortization, and blended vs unblended so a dollar means the same thing everywhere.
Attribution is filled from tags here; anything unmapped stays ``UNATTRIBUTED``.

Stub this session — build step 2.
"""

from __future__ import annotations

from typing import Any

from mcca.warehouse.models import FocusRecord


def normalize_records(raw: list[dict[str, Any]]) -> list[FocusRecord]:
    """Map raw AWS Cost Explorer records to normalized FOCUS records."""
    raise NotImplementedError("AWS -> FOCUS normalization lands in build step 2.")
