"""Unit tests for intent classifiers (T-E-2-01).

Covers KeywordHeuristicClassifier (pure, no I/O) and the Ollama fallback path
of OllamaIntentClassifier.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from rag_chat.application.pipeline.intent_classifier import (
    KeywordHeuristicClassifier,
    OllamaIntentClassifier,
)
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit


class TestKeywordHeuristicClassifier:
    def test_keyword_classifier_portfolio(self) -> None:
        """'my holdings' → PORTFOLIO intent."""
        clf = KeywordHeuristicClassifier()
        intent, sub_q, rephrased = clf.classify("What risks affect my holdings?")
        assert intent == QueryIntent.PORTFOLIO
        assert sub_q == []

    def test_keyword_classifier_comparison(self) -> None:
        """'compare X vs Y' → COMPARISON intent."""
        clf = KeywordHeuristicClassifier()
        intent, sub_q, _ = clf.classify("compare TSLA vs RIVN on gross margins")
        assert intent == QueryIntent.COMPARISON
        assert sub_q == []

    def test_keyword_classifier_reasoning(self) -> None:
        """'why is X' → REASONING intent."""
        clf = KeywordHeuristicClassifier()
        intent, _, _ = clf.classify("why is Apple's margin falling this quarter?")
        assert intent == QueryIntent.REASONING

    def test_keyword_classifier_default(self) -> None:
        """No keyword match → FACTUAL_LOOKUP (safe default)."""
        clf = KeywordHeuristicClassifier()
        intent, sub_q, rephrased = clf.classify("who is the CEO of Google?")
        assert intent == QueryIntent.FACTUAL_LOOKUP
        assert sub_q == []
        # rephrased_query is the original message on the keyword path
        assert rephrased == "who is the CEO of Google?"


class TestOllamaIntentClassifierFallback:
    async def test_ollama_classifier_falls_back_on_error(self) -> None:
        """Ollama timeout → keyword heuristic is used transparently."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        clf = OllamaIntentClassifier(
            ollama_base_url="http://localhost:11434",
            http_client=mock_client,
        )
        intent, sub_q, _ = await clf.classify("compare TSLA vs RIVN margins", [], [])

        # Fallback keyword classifier fires — "vs" → COMPARISON
        assert intent == QueryIntent.COMPARISON
        assert sub_q == []
        mock_client.post.assert_awaited_once()
