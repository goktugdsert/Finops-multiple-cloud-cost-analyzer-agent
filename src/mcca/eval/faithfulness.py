"""Prose numeric-faithfulness guard: every figure the agent states must come from a tool.

The trust boundary says the LLM never produces a cost figure of its own — every number
comes from a deterministic tool. That is enforced structurally for the SOURCE of numbers
(the agent can only reach the warehouse through the fixed query tools), but NOT for how the
model transcribes them into prose. This module closes that gap: it extracts the dollar
figures from the agent's final answer and checks each is traceable to a number that
actually appeared in a tool result. An untraceable figure is a fabrication (or a typo) and
fails faithfulness — e.g. it catches a hallucinated total that no query returned.

Only currency-shaped tokens are checked (a leading '$' or thousands grouping); bare counts,
years, horizons and percentages in prose are intentionally ignored, since the guarantee is
about reported COST FIGURES. Matching tolerates the model rounding a 10-dp warehouse value
to cents or whole dollars.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

# Currency-shaped tokens: a '$'-prefixed amount ("$76,401.98", "$29,807") or a
# thousands-grouped number ("29,219.62"). Bare integers/years without grouping are ignored.
_MONEY_RE = re.compile(r"\$\s?-?\d[\d,]*(?:\.\d+)?|-?\d{1,3}(?:,\d{3})+(?:\.\d+)?")


def _to_decimal(token: str) -> Decimal | None:
    cleaned = token.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def extract_reported_amounts(text: str) -> list[Decimal]:
    """Currency figures stated in a block of prose (the agent's final answer)."""
    amounts: list[Decimal] = []
    for token in _MONEY_RE.findall(text or ""):
        value = _to_decimal(token)
        if value is not None:
            amounts.append(value)
    return amounts


def _walk_numbers(value: Any) -> list[Decimal]:
    """All numeric values reachable inside a (parsed) tool result payload."""
    nums: list[Decimal] = []
    if isinstance(value, dict):
        for item in value.values():
            nums += _walk_numbers(item)
    elif isinstance(value, list):
        for item in value:
            nums += _walk_numbers(item)
    elif isinstance(value, bool):
        pass  # not a figure
    elif isinstance(value, (int, float)):
        nums.append(Decimal(str(value)))
    elif isinstance(value, str):
        parsed = _to_decimal(value)
        if parsed is not None:
            nums.append(parsed)
    return nums


def tool_amounts(tool_contents: list[str]) -> set[Decimal]:
    """Every numeric value that appeared in the given tool-result JSON payloads."""
    nums: set[Decimal] = set()
    for content in tool_contents:
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        nums.update(_walk_numbers(payload))
    return nums


def _is_traceable(reported: Decimal, available: set[Decimal]) -> bool:
    for tool_value in available:
        if reported == tool_value:
            return True
        # Tolerate the model rounding a 10-dp figure to cents or to whole dollars.
        if reported.quantize(Decimal("0.01")) == tool_value.quantize(Decimal("0.01")):
            return True
        if (
            reported.to_integral_value() == tool_value.to_integral_value()
            and abs(reported - tool_value) < 1
        ):
            return True
    return False


def untraceable_amounts(final_text: str, tool_contents: list[str]) -> list[str]:
    """Dollar figures in the answer that match no number any tool returned (fabrications).

    An empty list means every stated figure is grounded in a tool result.
    """
    available = tool_amounts(tool_contents)
    return [
        str(reported)
        for reported in extract_reported_amounts(final_text)
        if not _is_traceable(reported, available)
    ]


# --- Message-level guard (used at runtime by the CLI/web, and by the eval) --------------
def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def check_messages(messages: list[Any]) -> list[str]:
    """Untraceable figures in the final answer of a completed agent run (see above).

    Extracts the tool-result payloads and the final answer text from a LangGraph message
    list and returns any dollar figure the answer states that no tool produced.
    """
    from langchain_core.messages import ToolMessage

    tool_contents = [_flatten_content(m.content) for m in messages if isinstance(m, ToolMessage)]
    final_text = _flatten_content(messages[-1].content) if messages else ""
    return untraceable_amounts(final_text, tool_contents)


def warning_line(untraceable: list[str]) -> str:
    """A plain-text, user-facing caveat for untraceable figures (ASCII-only for terminals)."""
    figures = ", ".join(untraceable)
    return (
        "[faithfulness warning] These figure(s) could not be traced to any tool output and "
        f"may be unreliable: {figures}. Every reported number should come from a query or "
        "calculation; treat untraceable figures with caution."
    )
