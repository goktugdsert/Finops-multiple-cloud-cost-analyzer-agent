"""The RAG layer retrieves relevant qualitative passages — and can never supply a number."""

from __future__ import annotations

import re

from mcca.knowledge.corpus import DOCUMENTS
from mcca.knowledge.retriever import KeywordRetriever
from mcca.knowledge.service import search_knowledge

# A money-shaped token: a '$' or a thousands-grouped / decimal amount.
_MONEY = re.compile(r"\$|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+\.\d{2}\b")


def test_corpus_contains_no_cost_figures() -> None:
    # The single most important guardrail: RAG must never be able to supply a dollar figure.
    offenders = [d.id for d in DOCUMENTS if _MONEY.search(d.text)]
    assert not offenders, f"knowledge docs must be qualitative; money found in: {offenders}"


def test_retrieves_the_relevant_document() -> None:
    passages = search_knowledge("what is a savings plan and how do reservations work")
    assert passages
    top = passages[0]
    assert "commitment" in (top.title + top.text).lower()
    assert top.source.startswith("docs/")


def test_blended_query_finds_cost_measures_doc() -> None:
    passages = search_knowledge("difference between blended and unblended cost")
    titles = " ".join(p.title.lower() for p in passages)
    assert "cost measures" in titles


def test_scores_are_ranked_descending() -> None:
    passages = search_knowledge("allocation of shared unattributed spend across teams", k=5)
    scores = [p.score for p in passages]
    assert scores == sorted(scores, reverse=True)
    assert all(s > 0 for s in scores)


def test_irrelevant_query_returns_nothing() -> None:
    assert search_knowledge("purple elephant quantum zumba xyzzy") == []


def test_respects_k_limit() -> None:
    assert len(search_knowledge("cost", k=2)) <= 2


def test_retriever_is_pluggable_over_a_custom_corpus() -> None:
    from mcca.knowledge.corpus import Document

    docs = [Document("d", "Widgets", "docs/widgets", "A widget is a small gadget for testing.")]
    r = KeywordRetriever(docs)
    assert r.search("what is a widget")[0].title == "Widgets"
    assert r.search("savings plan") == []  # nothing in this corpus matches
