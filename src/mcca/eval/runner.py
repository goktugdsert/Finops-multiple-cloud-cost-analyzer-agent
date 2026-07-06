"""Run the curated eval set through the agent graph and grade tool selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from mcca.eval.dataset import EVAL_CASES, EvalCase


@dataclass(frozen=True)
class EvalResult:
    name: str
    passed: bool
    called_tools: list[str]
    expected: list[str]
    note: str


def collect_tool_calls(messages: list[Any]) -> list[str]:
    """Names of tools that actually executed during a run."""
    return [m.name for m in messages if isinstance(m, ToolMessage) and m.name]


def grade_case(case: EvalCase, messages: list[Any]) -> EvalResult:
    called = collect_tool_calls(messages)
    called_set = set(called)
    expected = sorted(case.expected_tools)
    if case.require_tool_use and not called_set:
        return EvalResult(
            case.name, False, called, expected, "no tool used (possible hallucination)"
        )
    if case.expected_tools and not case.expected_tools <= called_set:
        return EvalResult(case.name, False, called, expected, "expected tool not called")
    return EvalResult(case.name, True, called, expected, "ok")


def run_eval(graph: Any, cases: list[EvalCase] | None = None) -> list[EvalResult]:
    """Invoke the agent on each case and grade the resulting message trace."""
    cases = cases if cases is not None else EVAL_CASES
    results: list[EvalResult] = []
    for case in cases:
        try:
            out = graph.invoke({"messages": [HumanMessage(content=case.question)]})
            results.append(grade_case(case, out["messages"]))
        except Exception as exc:  # noqa: BLE001 - a failed run is a failed case
            results.append(EvalResult(case.name, False, [], sorted(case.expected_tools), str(exc)))
    return results


def summarize(results: list[EvalResult]) -> tuple[int, int]:
    return sum(r.passed for r in results), len(results)


def main() -> None:
    from mcca.agent.graph import build_agent_graph
    from mcca.agent.model import build_model
    from mcca.config import get_settings
    from mcca.logging import configure_logging
    from mcca.warehouse.postgres import PostgresRepository

    configure_logging()
    settings = get_settings()
    graph = build_agent_graph(PostgresRepository(), build_model(settings))

    results = run_eval(graph)
    passed, total = summarize(results)
    print(f"\nAgent eval — provider={settings.llm_provider}  model={settings.agent_model}\n")
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] {r.name:<24} called={r.called_tools or '-'}  ({r.note})")
    print(f"\nScore: {passed}/{total}")


if __name__ == "__main__":
    main()
