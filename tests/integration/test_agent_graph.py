"""Integration: the agent loop runs tools against Postgres and answers — no LLM key.

A scripted fake model stands in for Claude: it emits one `total_spend` tool call, then a
final answer. This exercises the REAL graph (model -> tools -> model), the REAL cost tools,
and the REAL warehouse queries, proving the wiring end-to-end without an Anthropic API key.
Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy.exc import OperationalError

from mcca.agent.graph import build_agent_graph
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import metadata

pytestmark = pytest.mark.integration

START = date(2026, 3, 1)
END = date(2026, 5, 1)


class ScriptedModel(BaseChatModel):
    """Fake Claude: one tool call to total_spend, then a final textual answer."""

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if any(isinstance(m, ToolMessage) for m in messages):
            msg = AIMessage(content="Your total billed spend was computed from total_spend.")
        else:
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "total_spend",
                        "args": {"start": START.isoformat(), "end": END.isoformat()},
                        "id": "call_1",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])


@pytest.fixture(scope="module")
def repo():
    engine = create_warehouse_engine(connect_args={"connect_timeout": 3})
    try:
        engine.connect().close()
    except OperationalError:
        pytest.skip("Postgres not reachable — run `docker compose up -d`.")
    metadata.drop_all(engine)
    metadata.create_all(engine)
    repository = PostgresRepository(engine=engine)
    seed_warehouse(repository, START, END, config=GeneratorConfig(seed=42))
    yield repository
    metadata.drop_all(engine)
    engine.dispose()


def test_agent_calls_tool_and_answers(repo: PostgresRepository) -> None:
    graph = build_agent_graph(repo, ScriptedModel())
    result = graph.invoke(
        {"messages": [HumanMessage(content="What did we spend in Mar-Apr 2026?")]}
    )
    messages = result["messages"]

    # A tool result for total_spend flowed back through the graph...
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    assert any(m.name == "total_spend" for m in tool_messages)
    assert "billed_cost" in tool_messages[0].content
    # ...and the run ends with a textual answer (no pending tool call).
    final = messages[-1]
    assert isinstance(final, AIMessage)
    assert not final.tool_calls
    assert "total_spend" in final.content
