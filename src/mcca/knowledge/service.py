"""Knowledge-search entry point: retrieve qualitative passages for a concept question.

NEVER returns a cost figure — the corpus is qualitative by construction (and tested to
contain no dollar amounts). For any number, callers use the deterministic query tools.
"""

from __future__ import annotations

from functools import lru_cache

from mcca.knowledge.corpus import DOCUMENTS
from mcca.knowledge.retriever import KeywordRetriever, Passage, Retriever


@lru_cache(maxsize=1)
def default_retriever() -> Retriever:
    """The built-in keyword retriever over the curated corpus (built once)."""
    return KeywordRetriever(DOCUMENTS)


def search_knowledge(
    query: str, k: int = 3, *, retriever: Retriever | None = None
) -> list[Passage]:
    """Return up to `k` relevant knowledge passages (qualitative only)."""
    return (retriever or default_retriever()).search(query, k=k)
