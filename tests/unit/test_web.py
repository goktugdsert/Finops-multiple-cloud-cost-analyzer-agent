"""The web chat UI serves a page and answers via the agent (fake model, no DB/LLM)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from mcca.surface.web import _message_text, create_app


class ScriptedModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if any(isinstance(m, ToolMessage) for m in messages):
            msg = AIMessage(content="Total billed spend was computed via total_spend.")
        else:
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "total_spend",
                        "args": {"start": "2026-01-01", "end": "2026-04-01"},
                        "id": "c1",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])


class FakeRepo:
    """execute() returns canned rows; build_report_data fails -> chat-only fallback page."""

    def execute(self, statement: Any) -> list[dict[str, Any]]:
        return [{"billed_cost": Decimal("123.45"), "effective_cost": Decimal("100.00")}]

    def create_schema(self) -> None: ...
    def insert_records(self, records: Any) -> int: ...
    def fetch_all(self) -> list[dict[str, Any]]: ...


def _client() -> TestClient:
    return TestClient(create_app(repo=FakeRepo(), model=ScriptedModel()))


def test_message_text_flattens_parts() -> None:
    assert _message_text("hi") == "hi"
    assert _message_text([{"text": "a"}, {"text": "b"}]) == "ab"


def test_index_serves_chat_ui() -> None:
    resp = _client().get("/")
    assert resp.status_code == 200
    assert "Ask the agent" in resp.text
    assert "/ask" in resp.text  # the fetch endpoint


def test_ask_runs_agent_and_returns_answer() -> None:
    resp = _client().post("/ask", json={"question": "How much did we spend?"})
    assert resp.status_code == 200
    body = resp.json()
    assert "total_spend" in body["answer"]


def _scripted(final_text: str) -> BaseChatModel:
    """A model that calls total_spend once, then answers with `final_text`."""

    class _M(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "scripted"

        def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
            if any(isinstance(m, ToolMessage) for m in messages):
                msg = AIMessage(content=final_text)
            else:
                msg = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "total_spend",
                            "args": {"start": "2026-01-01", "end": "2026-04-01"},
                            "id": "c1",
                        }
                    ],
                )
            return ChatResult(generations=[ChatGeneration(message=msg)])

    return _M()


def test_ask_flags_untraceable_figure_at_runtime() -> None:
    # The tool returns 123.45; the model fabricates $999,999.00 -> guard must warn.
    app = create_app(repo=FakeRepo(), model=_scripted("Our total was $999,999.00."))
    body = TestClient(app).post("/ask", json={"question": "total?"}).json()
    assert "warning" in body
    assert "999999.00" in body["warning"]
    assert "faithfulness warning" in body["answer"]  # surfaced to the user, not just logged


def test_ask_no_warning_when_every_figure_is_tool_sourced() -> None:
    # 123.45 IS the tool's billed_cost -> traceable -> no warning.
    app = create_app(repo=FakeRepo(), model=_scripted("Billed spend was $123.45."))
    body = TestClient(app).post("/ask", json={"question": "total?"}).json()
    assert "warning" not in body
    assert "123.45" in body["answer"]
