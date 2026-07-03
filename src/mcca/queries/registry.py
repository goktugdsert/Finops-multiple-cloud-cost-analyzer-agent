"""Registry of fixed, validated cost queries.

Build step 3 populates this with named query definitions (parameterized SQL over the
FOCUS warehouse) plus their expected parameters and result shapes. For now it is an
empty catalog with the lookup contract in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueryDefinition:
    """A single fixed, validated query the agent may run by name."""

    name: str
    description: str
    sql: str
    params: tuple[str, ...] = field(default_factory=tuple)


# Name -> definition. Populated in build step 3. Deliberately empty for now.
REGISTRY: dict[str, QueryDefinition] = {}


def get_query(name: str) -> QueryDefinition:
    """Look up a registered query by name."""
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise KeyError(
            f"Unknown query '{name}'. Only registered, validated queries may run; "
            "arbitrary SQL is not permitted."
        ) from exc
