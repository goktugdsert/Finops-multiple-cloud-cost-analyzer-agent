"""Eval grading: right tool passes; wrong/no tool fails (guards ungrounded answers)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from mcca.eval.dataset import EvalCase
from mcca.eval.runner import collect_tool_calls, grade_case


def _tool_msg(name: str) -> ToolMessage:
    return ToolMessage(content="{}", name=name, tool_call_id="x")


def test_collect_only_counts_executed_tools() -> None:
    messages = [AIMessage(content="hi"), _tool_msg("total_spend"), AIMessage(content="done")]
    assert collect_tool_calls(messages) == ["total_spend"]


def test_expected_tool_called_passes() -> None:
    case = EvalCase("t", "q", frozenset({"total_spend"}))
    result = grade_case(case, [_tool_msg("total_spend"), AIMessage(content="ok")])
    assert result.passed


def test_wrong_tool_fails() -> None:
    case = EvalCase("t", "q", frozenset({"total_spend"}))
    result = grade_case(case, [_tool_msg("spend_by_service"), AIMessage(content="ok")])
    assert not result.passed
    assert "expected tool" in result.note


def test_no_tool_use_fails_as_possible_hallucination() -> None:
    case = EvalCase("t", "How much did we spend?", frozenset({"total_spend"}))
    result = grade_case(case, [AIMessage(content="You spent $9,999.")])
    assert not result.passed
    assert "no tool" in result.note
