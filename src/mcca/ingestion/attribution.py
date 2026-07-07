"""Shared, cross-cloud allocation policy: cost-allocation tags -> FOCUS attribution.

Used by every provider's normalizer (AWS, Azure, GCP) so attribution means the same thing
regardless of cloud. Lines without a given tag keep the honest 'unattributed' default.
"""

from __future__ import annotations

# Tag key -> FOCUS x_* attribution column.
TAG_ATTRIBUTION: dict[str, str] = {
    "team": "x_team",
    "service": "x_service",
    "environment": "x_environment",
    "owner": "x_owner",
}


def attribution_from_tags(tags: dict[str, str] | None) -> dict[str, str]:
    """Derive the x_* attribution fields present in the tags (missing ones fall back)."""
    if not tags:
        return {}
    return {col: tags[key] for key, col in TAG_ATTRIBUTION.items() if tags.get(key)}
