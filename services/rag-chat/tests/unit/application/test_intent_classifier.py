"""Unit tests for intent classifiers (T-E-2-01).

Covers:
- KeywordHeuristicClassifier (pure, no I/O)
- OllamaIntentClassifier fallback path
- DeepInfraIntentClassifier happy path and fallback
- Usage logger integration (PLAN-0052 QA-R6 Item 2b)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from rag_chat.application.pipeline.intent_classifier import (
    DeepInfraIntentClassifier,
    KeywordHeuristicClassifier,
    OllamaIntentClassifier,
)
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit


def _make_usage_logger() -> AsyncMock:
    logger = AsyncMock()
    logger.log = AsyncMock()
    return logger


class TestKeywordHeuristicClassifier:
    def test_keyword_classifier_portfolio(self) -> None:
        """'my holdings' → PORTFOLIO intent."""
        clf = KeywordHeuristicClassifier()
        intent, sub_q, _ = clf.classify("What risks affect my holdings?")
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

    async def test_ollama_usage_logger_called_on_success(self) -> None:
        """usage_logger.log is called once per classify() call on the success path."""
        body = json.dumps({"intent": "FACTUAL_LOOKUP", "sub_questions": [], "rephrased_query": "who is CEO?"})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "response": body,
            "prompt_eval_count": 50,
            "eval_count": 10,
        }
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=resp)
        usage_logger = _make_usage_logger()

        clf = OllamaIntentClassifier(
            ollama_base_url="http://localhost:11434",
            http_client=mock_client,
            usage_logger=usage_logger,
        )
        await clf.classify("who is the CEO of Apple?", [], [])
        await asyncio.sleep(0)  # allow fire-and-forget task to execute

        usage_logger.log.assert_awaited_once()
        call_kwargs = usage_logger.log.call_args.kwargs
        assert call_kwargs["capability"] == "intent_classification"
        assert call_kwargs["provider"] == "ollama"
        assert call_kwargs["success"] is True
        assert call_kwargs["tokens_in"] == 50
        assert call_kwargs["tokens_out"] == 10

    async def test_ollama_usage_logger_called_on_fallback(self) -> None:
        """usage_logger.log is called even when Ollama errors and keyword fallback fires."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        usage_logger = _make_usage_logger()

        clf = OllamaIntentClassifier(
            ollama_base_url="http://localhost:11434",
            http_client=mock_client,
            usage_logger=usage_logger,
        )
        await clf.classify("compare TSLA vs RIVN", [], [])
        await asyncio.sleep(0)

        usage_logger.log.assert_awaited_once()
        call_kwargs = usage_logger.log.call_args.kwargs
        assert call_kwargs["success"] is False
        assert call_kwargs["error_code"] == "TimeoutException"


class TestDeepInfraIntentClassifier:
    """Tests for DeepInfraIntentClassifier (GPU-based primary classifier)."""

    def _make_mock_response(self, intent: str, sub_questions: list | None = None, rephrased: str = "") -> MagicMock:
        """Build a mock httpx response with DeepInfra chat completions format."""
        content = json.dumps({"intent": intent, "sub_questions": sub_questions, "rephrased_query": rephrased})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        return resp

    async def test_deepinfra_classifier_happy_path(self) -> None:
        """DeepInfra returns valid JSON → intent is parsed correctly."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            return_value=self._make_mock_response(
                "COMPARISON",
                sub_questions=["What are Tesla margins?", "What are Rivian margins?"],
                rephrased="Compare TSLA and RIVN gross margins.",
            )
        )
        clf = DeepInfraIntentClassifier(
            api_key="test-key",
            http_client=mock_client,
        )
        intent, sub_q, rephrased = await clf.classify("Compare TSLA vs RIVN margins", [], [])

        assert intent == QueryIntent.COMPARISON
        assert len(sub_q) == 2
        assert "Tesla" in sub_q[0]
        assert rephrased == "Compare TSLA and RIVN gross margins."

    async def test_deepinfra_classifier_falls_back_on_http_error(self) -> None:
        """DeepInfra HTTP error → keyword heuristic fallback fires."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=MagicMock())
        )
        clf = DeepInfraIntentClassifier(api_key="bad-key", http_client=mock_client)
        intent, sub_q, _ = await clf.classify("my portfolio holdings", [], [])

        # Falls back to keyword heuristic — "portfolio" → PORTFOLIO
        assert intent == QueryIntent.PORTFOLIO
        assert sub_q == []

    async def test_deepinfra_classifier_falls_back_on_timeout(self) -> None:
        """DeepInfra timeout → keyword heuristic fallback fires."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        clf = DeepInfraIntentClassifier(api_key="test-key", http_client=mock_client)
        intent, _, _ = await clf.classify("why is Apple's margin falling?", [], [])

        # Falls back to keyword — "why" → REASONING
        assert intent == QueryIntent.REASONING

    async def test_deepinfra_classifier_invalid_intent_defaults_to_factual(self) -> None:
        """Model returns unrecognized intent string → defaults to FACTUAL_LOOKUP."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        bad_resp = MagicMock()
        bad_resp.raise_for_status = MagicMock()
        bad_resp.json.return_value = {
            "choices": [
                {"message": {"content": '{"intent": "UNKNOWN_INTENT", "sub_questions": [], "rephrased_query": ""}'}}
            ]
        }
        mock_client.post = AsyncMock(return_value=bad_resp)
        clf = DeepInfraIntentClassifier(api_key="test-key", http_client=mock_client)
        intent, sub_q, _ = await clf.classify("who is the CEO?", [], [])

        assert intent == QueryIntent.FACTUAL_LOOKUP
        assert sub_q == []

    async def test_deepinfra_classifier_posts_to_correct_url(self) -> None:
        """Verify the request is sent to DeepInfra's OpenAI-compat endpoint."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=self._make_mock_response("FACTUAL_LOOKUP"))
        clf = DeepInfraIntentClassifier(api_key="test-key-abc", http_client=mock_client)
        await clf.classify("who is the CEO of Apple?", [], [])

        call_args = mock_client.post.call_args
        url: str = call_args[0][0]
        assert "deepinfra.com" in url
        assert "chat/completions" in url

        # Authorization header must be present via kwargs
        posted_kwargs = mock_client.post.call_args.kwargs
        assert "Bearer test-key-abc" in posted_kwargs.get("headers", {}).get("Authorization", "")

    async def test_deepinfra_classifier_default_model_is_available(self) -> None:
        """PLAN-0052 platform-QA round 5: default model is the 1B (was 8B).

        The 1B is ~6x cheaper for the small intent-classification task.
        Both `meta-llama/Llama-3.2-1B-Instruct` and the legacy 8B are
        confirmed available on the project's DeepInfra account; the 1B
        is the right default for cost/latency, the 8B is available as
        a config override for installs that need higher accuracy."""
        clf = DeepInfraIntentClassifier(api_key="test")
        assert clf._model == "meta-llama/Llama-3.2-1B-Instruct"

    async def test_deepinfra_usage_logger_called_on_success(self) -> None:
        """usage_logger.log is called once per classify() on the happy path."""
        content = json.dumps({"intent": "FACTUAL_LOOKUP", "sub_questions": [], "rephrased_query": ""})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=resp)
        usage_logger = _make_usage_logger()

        clf = DeepInfraIntentClassifier(api_key="test-key", http_client=mock_client, usage_logger=usage_logger)
        await clf.classify("who is the CEO of Apple?", [], [])
        await asyncio.sleep(0)  # let fire-and-forget task execute

        usage_logger.log.assert_awaited_once()
        kwargs = usage_logger.log.call_args.kwargs
        assert kwargs["capability"] == "intent_classification"
        assert kwargs["provider"] == "deepinfra"
        assert kwargs["success"] is True
        assert kwargs["tokens_in"] == 120
        assert kwargs["tokens_out"] == 30
        assert kwargs["error_code"] is None

    async def test_deepinfra_usage_logger_called_on_failure(self) -> None:
        """usage_logger.log fires with success=False when DeepInfra errors."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        usage_logger = _make_usage_logger()

        clf = DeepInfraIntentClassifier(api_key="test-key", http_client=mock_client, usage_logger=usage_logger)
        await clf.classify("latest news on NVDA", [], [])
        await asyncio.sleep(0)

        usage_logger.log.assert_awaited_once()
        kwargs = usage_logger.log.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error_code"] == "TimeoutException"
        assert kwargs["tokens_in"] == 0

    async def test_no_usage_logger_no_error(self) -> None:
        """usage_logger=None (default) — classifier works normally."""
        content = json.dumps({"intent": "GENERAL", "sub_questions": [], "rephrased_query": ""})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": content}}], "usage": {}}
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=resp)

        clf = DeepInfraIntentClassifier(api_key="test-key", http_client=mock_client)
        intent, _, _ = await clf.classify("how do interest rates work?", [], [])
        assert intent == QueryIntent.GENERAL
