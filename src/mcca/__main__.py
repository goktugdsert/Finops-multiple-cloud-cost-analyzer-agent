"""CLI entry point and composition root for the agent.

Wires the concrete warehouse repository + Anthropic model into the LangGraph agent and
answers a question. This top-level module is the only place allowed to import across all
layers; the agent package itself stays dependency-clean.

    uv run mcca "What did we spend by service last month?"
"""

from __future__ import annotations

import sys

from langchain_core.messages import HumanMessage

from mcca.agent.graph import build_agent_graph
from mcca.agent.model import build_model
from mcca.config import get_settings
from mcca.eval.faithfulness import check_messages, warning_line
from mcca.logging import configure_logging
from mcca.tracing import flush_tracing, tracing_config
from mcca.warehouse.postgres import PostgresRepository


def main() -> None:
    configure_logging()
    settings = get_settings()

    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('Usage: uv run mcca "<your cost question>"')
        print("Seed demo data first with: uv run mcca-seed")
        return

    repo = PostgresRepository()
    try:
        model = build_model(settings)
        graph = build_agent_graph(repo, model)
        result = graph.invoke(
            {"messages": [HumanMessage(content=question)]}, config=tracing_config(settings)
        )
        flush_tracing(settings)
    except Exception as exc:  # noqa: BLE001 - surface a friendly setup hint
        flush_tracing(settings)  # still record the (errored) run in Langfuse
        print(f"Agent run failed: {exc}")
        print(
            f"Provider is MCCA_LLM_PROVIDER={settings.llm_provider!r}. Check its key/quota "
            "in .env (google=MCCA_GOOGLE_API_KEY, ollama=local server), and ensure Postgres "
            "is up (docker compose up -d) and seeded (uv run mcca-seed)."
        )
        return

    messages = result["messages"]
    print(_render(messages[-1].content))

    # Runtime faithfulness guard: warn if the answer states a figure no tool produced.
    untraceable = check_messages(messages)
    if untraceable:
        print("\n" + warning_line(untraceable))


def _render(content: object) -> str:
    """Flatten a chat message's content (str or list-of-parts) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        ]
        return "".join(p for p in parts if p)
    return str(content)


if __name__ == "__main__":
    main()
