"""Unit tests for KeywordHeuristicClassifier vocabulary coverage.

F-NEW-014 (2026-06-05): the size & capital structure category was missing from
`_INTENT_KEYWORDS[FINANCIAL_DATA]`. 9 of 14 financial phrasings routed to GENERAL
or FACTUAL_LOOKUP instead of FINANCIAL_DATA, breaking ~80% of valuation queries.

These tests pin the post-fix behavior: each phrasing now routes to FINANCIAL_DATA.
"""

from __future__ import annotations

import pytest
from rag_chat.application.pipeline.intent_classifier import KeywordHeuristicClassifier
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit


@pytest.fixture
def classifier() -> KeywordHeuristicClassifier:
    return KeywordHeuristicClassifier()


# ── F-NEW-014 regression: size & capital structure phrasings ──────────────────


@pytest.mark.parametrize(
    "query",
    [
        "What is Apple's market cap?",
        "What is Apple's market capitalization?",
        "What is NVDA's enterprise value?",
        "How many shares outstanding does AMD have?",
        "What's MSFT's book value?",
        "What's the net debt at TSLA?",
        "What's the beta on Apple?",
        "What's Apple's ROIC?",
        "Show me Apple's float",
    ],
)
def test_size_and_capital_structure_phrases_route_to_financial_data(
    classifier: KeywordHeuristicClassifier, query: str
) -> None:
    """F-NEW-014: these 9 phrasings previously routed to GENERAL/FACTUAL_LOOKUP.

    Regression guard: each must now route to FINANCIAL_DATA.
    """
    intent, _, _ = classifier.classify(query)
    assert intent == QueryIntent.FINANCIAL_DATA, f"query={query!r} routed to {intent}"


# ── Non-regression: previously-working financial phrasings still work ─────────


@pytest.mark.parametrize(
    "query",
    [
        "What's Apple's dividend yield?",
        "What's the PEG ratio on NVDA?",
        "What's MSFT's operating margin?",
        "What is TSLA's current P/E ratio?",
        "What's Apple's revenue?",
        "What's NVDA's EBITDA?",
    ],
)
def test_existing_financial_phrases_still_route_correctly(classifier: KeywordHeuristicClassifier, query: str) -> None:
    """Ensure F-NEW-014 keyword additions did not displace pre-existing matches."""
    intent, _, _ = classifier.classify(query)
    assert intent == QueryIntent.FINANCIAL_DATA, f"query={query!r} routed to {intent}"


# ── Non-regression: bare "ev" intentionally NOT added (would false-positive) ──


def test_bare_ev_does_not_falsely_route_electric_vehicle_query(
    classifier: KeywordHeuristicClassifier,
) -> None:
    """Bare token "ev" is intentionally excluded — only "ev/ebitda", "ev/revenue",
    "ev/sales" ratios are matched. A query about Tesla EVs must not route to
    FINANCIAL_DATA via this vocab (it falls through to FACTUAL_LOOKUP default)."""
    intent, _, _ = classifier.classify("Tell me about Tesla EV deliveries")
    # "tell me about" matches GENERAL — verify we did NOT hit FINANCIAL_DATA via bare "ev".
    assert intent != QueryIntent.FINANCIAL_DATA
