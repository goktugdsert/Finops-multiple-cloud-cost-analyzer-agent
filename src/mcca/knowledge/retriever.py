"""Retriever interface + a dependency-free lexical implementation.

The `Retriever` interface is the seam (like WarehouseRepository): the default
`KeywordRetriever` scores passages by inverse-document-frequency-weighted term overlap — no
embedding model, no pgvector, no external service, which fits the free/local constraint and
is plenty for a small curated corpus. A pgvector/embedding backend can be swapped in later
behind this same interface without touching the tool or agent layers.
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass

from mcca.knowledge.corpus import Document

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "are",
    "was",
    "our",
    "you",
    "your",
    "from",
    "into",
    "over",
    "per",
    "its",
    "it",
    "is",
    "of",
    "to",
    "in",
    "on",
    "as",
    "at",
    "by",
    "be",
    "an",
    "or",
    "we",
    "a",
    "how",
    "does",
    "do",
    "what",
    "why",
    "which",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2 and t not in _STOPWORDS]


@dataclass(frozen=True)
class Passage:
    title: str
    source: str
    text: str
    score: float


class Retriever(ABC):
    @abstractmethod
    def search(self, query: str, k: int = 3) -> list[Passage]:
        """Return up to `k` passages most relevant to `query` (empty if none match)."""


class KeywordRetriever(Retriever):
    """Lexical retriever: idf-weighted term overlap over passage-level chunks."""

    def __init__(self, documents: list[Document]) -> None:
        self._passages: list[tuple[Document, str, Counter]] = []
        for doc in documents:
            for para in (p.strip() for p in doc.text.split("\n\n")):
                if para:
                    self._passages.append((doc, para, Counter(_tokens(para))))

        n = len(self._passages) or 1
        df: Counter = Counter()
        for _, _, counts in self._passages:
            df.update(counts.keys())
        self._idf = {term: math.log(1 + n / freq) for term, freq in df.items()}

    def search(self, query: str, k: int = 3) -> list[Passage]:
        q_terms = set(_tokens(query))
        if not q_terms:
            return []
        scored: list[Passage] = []
        for doc, text, counts in self._passages:
            score = sum(
                self._idf.get(term, 0.0) * (1 + math.log(counts[term]))
                for term in q_terms
                if counts.get(term)
            )
            if score > 0:
                scored.append(Passage(doc.title, doc.source, text, round(score, 3)))
        scored.sort(key=lambda p: p.score, reverse=True)
        return scored[:k]
