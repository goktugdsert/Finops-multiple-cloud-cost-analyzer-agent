"""Agent graph state: the running message list, with LangGraph's reducer."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State threaded through the graph. `add_messages` appends across nodes."""

    messages: Annotated[list, add_messages]
