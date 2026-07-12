"""Run the curated eval set through the agent graph and grade tool selection."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from mcca.eval.dataset import EVAL_CASES, EvalCase
from mcca.eval.faithfulness import check_messages


@dataclass(frozen=True)
class EvalResult:
    name: str
    passed: bool
    called_tools: list[str]
    expected: list[str]
    note: str
    # Dollar figures in the final answer that trace to NO tool output (fabrications).
    # Empty means every stated number is grounded in a deterministic tool result.
    untraceable_numbers: list[str] = field(default_factory=list)


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


def run_eval(
    graph: Any, cases: list[EvalCase] | None = None, *, config: dict[str, Any] | None = None
) -> list[EvalResult]:
    """Invoke the agent on each case and grade the resulting message trace."""
    cases = cases if cases is not None else EVAL_CASES
    results: list[EvalResult] = []
    for case in cases:
        try:
            out = graph.invoke({"messages": [HumanMessage(content=case.question)]}, config=config)
            result = grade_case(case, out["messages"])
            results.append(replace(result, untraceable_numbers=check_messages(out["messages"])))
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
    from mcca.tracing import flush_tracing, tracing_config
    from mcca.warehouse.postgres import PostgresRepository

    configure_logging()
    settings = get_settings()
    graph = build_agent_graph(PostgresRepository(), build_model(settings))

    results = run_eval(graph, config=tracing_config(settings))
    flush_tracing(settings)
    passed, total = summarize(results)
    print(f"\nAgent eval — provider={settings.llm_provider}  model={settings.agent_model}\n")
    unfaithful = 0
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] {r.name:<24} called={r.called_tools or '-'}  ({r.note})")
        if r.untraceable_numbers:
            unfaithful += 1
            print(f"         !! untraceable figure(s) not from any tool: {r.untraceable_numbers}")
    print(f"\nTool-selection score: {passed}/{total}")
    print(
        f"Numeric faithfulness: {total - unfaithful}/{total} answers "
        "stated only tool-sourced figures"
    )


if __name__ == "__main__":
    main()
