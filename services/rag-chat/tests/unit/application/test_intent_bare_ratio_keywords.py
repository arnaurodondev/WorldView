"""PLAN-0104 W49 — bare-ratio / margin / cash-flow / growth route to FINANCIAL_DATA.

Round 8 benchmark Q1 ("What's AAPL's P/E ratio?") and Q5 GOOGL classified as
GENERAL, which skips the FINANCIAL_DATA addendum (4-section ANSWER STRUCTURE
from W31) and produces one-liners instead of the mandated structure. W49
extends the keyword heuristic with bare-ratio names ("p/e ratio"),
price-multiple ratios, margins, cash-flow, growth, and per-share metrics so
the fallback path always routes to the snapshot-aware toolchain.

Also pins the negative cases: PORTFOLIO / COMPARISON / REASONING /
RELATIONSHIP must still win over FINANCIAL_DATA on ambiguous phrases
(first-match-wins).
"""

from __future__ import annotations

import pytest
from rag_chat.application.pipeline.intent_classifier import (
    KeywordHeuristicClassifier,
)
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit


# Round 8 questions + extra coverage. Each must classify as FINANCIAL_DATA.
@pytest.mark.parametrize(
    "message",
    [
        # Round 8 explicit set
        "What's AAPL's P/E ratio?",
        "Show me Meta's EPS over the last 4 quarters.",
        "What's Amazon's YoY revenue growth?",
        "How has Tesla's gross margin trended in the last year?",
        # Note: "Is GOOGL expensive vs its history?" deliberately omitted —
        # COMPARISON wins (first-match on " vs ") which is the correct
        # first-match-wins ordering per W49 constraints.
        "Is GOOGL expensive?",  # bare "expensive" → FINANCIAL_DATA (W30)
        "What's AAPL's forward P/E?",  # W30 still covered
        # Additional ratio coverage (W49)
        "MSFT EV/EBITDA today",
        "Show me NVDA's price-to-book",
        "What is META's dividend yield?",
        "ROE for JPM?",
        "Show me Apple's payout ratio",
        # Margins
        "What's Tesla's operating margin?",
        "Microsoft net margin trend",
        "AMD EBITDA margin last quarter",
        # Cash flow
        "Amazon free cash flow last year",
        "What's AAPL's FCF?",
        "Show me Google's capex",
        # Growth
        "NVDA eps growth QoQ",
        "META QoQ growth",
    ],
)
def test_bare_ratio_and_metric_questions_route_to_financial_data(message: str) -> None:
    """W49: each metric / ratio / margin / cash-flow / growth phrase
    must route to FINANCIAL_DATA, never to GENERAL."""
    classifier = KeywordHeuristicClassifier()
    intent, _sub, _rephrased = classifier.classify(message)
    assert intent is QueryIntent.FINANCIAL_DATA, f"{message!r} routed to {intent.value}; expected FINANCIAL_DATA"


# Negative cases — ensure W49 broadening does NOT swallow specific intents.
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # PORTFOLIO must still win even when "revenue" or "ratio" appears.
        ("What's my portfolio's revenue exposure?", QueryIntent.PORTFOLIO),
        ("Show me my holdings P/E ratio average", QueryIntent.PORTFOLIO),
        # COMPARISON must still win even with ratio vocab.
        ("Compare TSLA vs RIVN gross margin", QueryIntent.COMPARISON),
        ("AAPL vs MSFT P/E", QueryIntent.COMPARISON),
        # REASONING must still win.
        ("Why is Tesla's gross margin declining?", QueryIntent.REASONING),
        ("Explain why AAPL P/E is high", QueryIntent.REASONING),
        # RELATIONSHIP must still win.
        ("What is Apple's supply chain relationship with TSMC?", QueryIntent.RELATIONSHIP),
    ],
)
def test_higher_priority_intents_still_win_over_financial_data(message: str, expected: QueryIntent) -> None:
    """W49 negative path: first-match-wins ordering keeps PORTFOLIO,
    COMPARISON, REASONING, RELATIONSHIP ahead of FINANCIAL_DATA so the
    broader keyword list does not steal their queries."""
    classifier = KeywordHeuristicClassifier()
    intent, _sub, _rephrased = classifier.classify(message)
    assert intent is expected, f"{message!r} routed to {intent.value}; expected {expected.value}"
