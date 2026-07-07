"""LangGraph agent: an LLM that reasons and calls cost tools, looping until answered.

The graph is the canonical tool-calling loop:

    START -> model -> (tools? -> tools -> model)* -> END

`model` invokes the tool-bound LLM; `tools` executes any requested cost queries and feeds
results back. The LLM's only way to obtain a number is a tool call, so the core principle
holds structurally. This module imports ONLY the tools layer (+ prompts/state) — never
ingestion, boto3, or SQL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from mcca.agent.prompts import SYSTEM_PROMPT
from mcca.agent.state import AgentState
from mcca.tools.cost_tools import catalog_hint, get_cost_tools

if TYPE_CHECKING:
    from mcca.warehouse.repository import WarehouseRepository


def build_agent_graph(
    repo: WarehouseRepository, model: Any, *, system_prompt: str = SYSTEM_PROMPT
) -> Any:
    """Compile the agent graph over the cost tools, bound to a warehouse repository."""
    tools = get_cost_tools(repo)
    model_with_tools = model.bind_tools(tools)

    # Ground the prompt with the exact service names present, so the model doesn't guess.
    catalog = catalog_hint(repo)
    prompt = f"{system_prompt}\n\n{catalog}" if catalog else system_prompt

    def call_model(state: AgentState) -> dict[str, Any]:
        messages = list(state["messages"])
        if not messages or getattr(messages[0], "type", None) != "system":
            messages = [SystemMessage(content=prompt), *messages]
        return {"messages": [model_with_tools.invoke(messages)]}

    builder = StateGraph(AgentState)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "model")
    # tools_condition routes to "tools" when the model requested a tool call, else to END.
    builder.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "model")
    return builder.compile()
