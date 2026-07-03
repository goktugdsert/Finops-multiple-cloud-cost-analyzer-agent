"""Agent graph state. Fleshed out in build step 4."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """State threaded through the LangGraph graph."""

    question: str
    messages: list[Any]
    # Figures returned to the user, each tagged with the query that produced it.
    results: list[dict[str, Any]]
