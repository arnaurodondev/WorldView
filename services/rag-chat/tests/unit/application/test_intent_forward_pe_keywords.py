"""PLAN-0104 W30 / BP-650 — forward-valuation vocabulary routes to FINANCIAL_DATA.

Round 3 benchmark Q6 ("What's AAPL forward P/E?") graded USELESS because
the keyword heuristic classified it as GENERAL → zero tools fired → flat
refusal. W30 adds "forward p/e", "forward pe", "peg", "valuation",
"expensive", "cheap", "overvalued", "undervalued" to the FINANCIAL_DATA
keyword list so the fallback path always routes to the snapshot-aware
toolchain.
"""

from __future__ import annotations

import pytest
from rag_chat.application.pipeline.intent_classifier import (
    KeywordHeuristicClassifier,
)
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "message",
    [
        "What's AAPL forward P/E?",
        "What is AAPL forward PE?",
        "TSLA PEG ratio",
        "NVDA valuation today",
        "Is TSLA expensive right now?",
        "Looks cheap to me",
        "Is AAPL overvalued?",
        "Is META undervalued today?",
    ],
)
def test_forward_valuation_vocabulary_routes_to_financial_data(message: str) -> None:
    """Each forward-valuation phrase must map to FINANCIAL_DATA, not GENERAL."""
    classifier = KeywordHeuristicClassifier()
    intent, _sub, _rephrased = classifier.classify(message)
    assert intent is QueryIntent.FINANCIAL_DATA, f"{message!r} routed to {intent.value}; expected FINANCIAL_DATA"
