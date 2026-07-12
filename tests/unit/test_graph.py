"""The agent graph nudges once when the model returns an empty final answer (no DB/LLM)."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from mcca.agent.graph import build_agent_graph

_NUDGE = "Summarize the answer"


class FakeRepo:
    def execute(self, statement: Any) -> list[dict[str, Any]]:
        return []

    def create_schema(self) -> None: ...
    def insert_records(self, records: Any) -> int:
        return 0

    def upsert_records(self, records: Any) -> int:
        return 0

    def fetch_all(self) -> list[dict[str, Any]]:
        return []


class EmptyThenText(BaseChatModel):
    """Returns an empty final answer first; after the retry nudge, returns text."""

    @property
    def _llm_type(self) -> str:
        return "empty-then-text"

    def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        last = messages[-1]
        nudged = isinstance(last, HumanMessage) and _NUDGE in str(last.content)
        content = "Here is your grounded answer." if nudged else ""
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


class AlwaysText(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "always-text"

    def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Direct answer."))])


def _run(model: BaseChatModel) -> str:
    graph = build_agent_graph(FakeRepo(), model)
    out = graph.invoke({"messages": [HumanMessage(content="What did we spend?")]})
    return out["messages"][-1].content


def test_empty_final_answer_is_retried_once() -> None:
    assert _run(EmptyThenText()) == "Here is your grounded answer."


def test_non_empty_answer_is_not_retried() -> None:
    assert _run(AlwaysText()) == "Direct answer."
