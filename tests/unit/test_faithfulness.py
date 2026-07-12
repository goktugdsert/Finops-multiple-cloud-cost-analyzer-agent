"""The prose-faithfulness guard flags dollar figures that no tool actually returned.

This is the transcription half of the trust boundary: sourcing is enforced structurally
(the agent can only get numbers from tools), and this guard catches the model *stating* a
number that isn't in any tool result. No DB or LLM needed.
"""

from __future__ import annotations

import json
from decimal import Decimal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from mcca.eval.faithfulness import (
    check_messages,
    extract_reported_amounts,
    tool_amounts,
    untraceable_amounts,
    warning_line,
)

# A realistic total_spend tool payload (values are 10-dp strings, as serialized).
TOTAL_SPEND_TOOL = json.dumps(
    {
        "query": "total_spend",
        "params": {"start": "2026-01-01", "end": "2026-04-01"},
        "rows": [{"billed_cost": "76401.9800000000", "effective_cost": "66706.1700000000"}],
    }
)


def test_extract_ignores_non_currency_numbers() -> None:
    text = "In 2026 the top 3 services grew 15% to $29,219.62 over 30 days."
    # Only the dollar figure is treated as a reported amount (not 2026, 3, 15, 30).
    assert extract_reported_amounts(text) == [Decimal("29219.62")]


def test_faithful_answer_has_no_untraceable_figures() -> None:
    answer = "From Jan 1 to Apr 1, 2026 you spent $76,401.98 billed and $66,706.17 effective."
    assert untraceable_amounts(answer, [TOTAL_SPEND_TOOL]) == []


def test_whole_dollar_rounding_is_tolerated() -> None:
    # Model rounds the 10-dp figure to whole dollars — still traceable.
    answer = "Roughly $76,402 in total."
    assert untraceable_amounts(answer, [TOTAL_SPEND_TOOL]) == []


def test_fabricated_figure_is_flagged() -> None:
    # $80,000 appears in no tool output -> a fabrication the guard must catch.
    answer = "You spent about $80,000.00 in total."
    assert untraceable_amounts(answer, [TOTAL_SPEND_TOOL]) == ["80000.00"]


def test_no_tools_means_any_stated_figure_is_untraceable() -> None:
    answer = "You spent $9,999.00."
    assert untraceable_amounts(answer, []) == ["9999.00"]


def test_tool_amounts_walks_nested_rows() -> None:
    cents = {n.quantize(Decimal("0.01")) for n in tool_amounts([TOTAL_SPEND_TOOL])}
    assert Decimal("76401.98") in cents
    assert Decimal("66706.17") in cents


def _run(final_text: str) -> list:
    """A minimal completed agent message trace: human -> tool result -> final answer."""
    return [
        HumanMessage(content="How much did we spend?"),
        ToolMessage(content=TOTAL_SPEND_TOOL, name="total_spend", tool_call_id="c1"),
        AIMessage(content=final_text),
    ]


def test_check_messages_flags_fabricated_final_answer() -> None:
    assert check_messages(_run("You spent $80,000.00.")) == ["80000.00"]


def test_check_messages_passes_faithful_final_answer() -> None:
    assert check_messages(_run("You spent $76,401.98 billed.")) == []


def test_warning_line_names_the_untraceable_figures() -> None:
    warning = warning_line(["80000.00"])
    assert "80000.00" in warning
    assert "faithfulness" in warning.lower()
