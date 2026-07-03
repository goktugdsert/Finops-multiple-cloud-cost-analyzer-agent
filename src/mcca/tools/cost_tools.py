"""Cost tools exposed to the agent.

Build step 4 wraps registered queries (queries/registry.py) as LangChain tools so the
LangGraph agent can call them. Every returned figure is traceable to a named query.
Stub this session.
"""

from __future__ import annotations

from typing import Any


def get_cost_tools() -> list[Any]:
    """Return the LangChain tools the agent may call. Empty until build step 4."""
    return []
