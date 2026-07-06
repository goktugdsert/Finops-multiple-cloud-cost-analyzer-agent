"""Integration: the eval runner grades a real agent run (scripted model, no LLM key).

Requires `docker compose up -d`; skips if Postgres is unreachable.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy.exc import OperationalError

from mcca.agent.graph import build_agent_graph
from mcca.eval.dataset import EvalCase
from mcca.eval.runner import run_eval, summarize
from mcca.ingestion.synthetic.generator import GeneratorConfig
from mcca.ingestion.synthetic.seed import seed_warehouse
from mcca.warehouse.engine import create_warehouse_engine
from mcca.warehouse.postgres import PostgresRepository
from mcca.warehouse.schema import metadata

pytestmark = pytest.mark.integration

START = date(2026, 1, 1)
END = date(2026, 3, 1)


class ScriptedModel(BaseChatModel):
    """Always calls total_spend once, then answers — a deterministic stand-in."""

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if any(isinstance(m, ToolMessage) for m in messages):
            msg = AIMessage(content="Total computed via total_spend.")
        else:
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "total_spend",
                        "args": {"start": "2026-01-01", "end": "2026-03-01"},
                        "id": "c1",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])


@pytest.fixture(scope="module")
def graph():
    engine = create_warehouse_engine(connect_args={"connect_timeout": 3})
    try:
        engine.connect().close()
    except OperationalError:
        pytest.skip("Postgres not reachable — run `docker compose up -d`.")
    metadata.drop_all(engine)
    metadata.create_all(engine)
    repo = PostgresRepository(engine=engine)
    seed_warehouse(repo, START, END, config=GeneratorConfig(seed=42))
    yield build_agent_graph(repo, ScriptedModel())
    metadata.drop_all(engine)
    engine.dispose()


def test_eval_runner_grades_a_real_run(graph) -> None:
    cases = [EvalCase("total", "How much did we spend?", frozenset({"total_spend"}))]
    results = run_eval(graph, cases)
    passed, total = summarize(results)
    assert (passed, total) == (1, 1)
    assert results[0].called_tools == ["total_spend"]
