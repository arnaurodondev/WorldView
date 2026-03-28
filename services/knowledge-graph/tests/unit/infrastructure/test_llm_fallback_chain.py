"""Unit tests for FallbackChainClient (T-D-3-09)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


def _make_embedding_client(*, fail: bool = False) -> AsyncMock:
    client = AsyncMock()
    client.model_id = "test-model"
    if fail:
        client.embed = AsyncMock(side_effect=RuntimeError("provider down"))
    else:
        from ml_clients.dataclasses import EmbeddingOutput

        client.embed = AsyncMock(return_value=[EmbeddingOutput(embedding=[0.1] * 10, model_id="test", dimension=10)])
    return client


def _make_extraction_client(*, fail: bool = False) -> AsyncMock:
    from ml_clients.dataclasses import ExtractionOutput

    client = AsyncMock()
    client.model_id = "test-model"
    if fail:
        client.extract = AsyncMock(side_effect=RuntimeError("provider down"))
    else:
        client.extract = AsyncMock(
            return_value=ExtractionOutput(result={"summary": "ok"}, raw_response="ok", model_id="test")
        )
    return client


class TestFallbackChainClientEmbedding:
    def test_ollama_success_no_fallback(self) -> None:
        """Ollama succeeds → Gemini never called."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

        ollama = _make_embedding_client()
        gemini = _make_embedding_client()
        client = FallbackChainClient(
            ollama_embedding=ollama,
            gemini_embedding=gemini,
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )

        result = asyncio.get_event_loop().run_until_complete(client.embed([]))
        ollama.embed.assert_awaited_once()
        gemini.embed.assert_not_awaited()
        assert result is not None

    def test_ollama_fail_gemini_called(self) -> None:
        """Ollama fails → Gemini is called."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

        ollama = _make_embedding_client(fail=True)
        gemini = _make_embedding_client()
        client = FallbackChainClient(
            ollama_embedding=ollama,
            gemini_embedding=gemini,
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )

        result = asyncio.get_event_loop().run_until_complete(client.embed([]))
        assert result is not None
        gemini.embed.assert_awaited_once()

    def test_both_fail_returns_none(self) -> None:
        """Both chains exhausted → None returned."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

        ollama = _make_embedding_client(fail=True)
        gemini = _make_embedding_client(fail=True)
        client = FallbackChainClient(
            ollama_embedding=ollama,
            gemini_embedding=gemini,
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )

        result = asyncio.get_event_loop().run_until_complete(client.embed([]))
        assert result is None

    def test_no_clients_returns_none(self) -> None:
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

        client = FallbackChainClient(retry_delays_ollama=(), retry_delays_gemini=())
        result = asyncio.get_event_loop().run_until_complete(client.embed([]))
        assert result is None


class TestFallbackChainClientExtraction:
    def test_extraction_ollama_success(self) -> None:
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import ExtractionInput

        ollama = _make_extraction_client()
        client = FallbackChainClient(
            ollama_extraction=ollama,
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = ExtractionInput(prompt="p", context="c", output_schema={}, model_id="m")
        result = asyncio.get_event_loop().run_until_complete(client.extract(inp))
        assert result is not None
        assert result.result == {"summary": "ok"}

    def test_extraction_fallback_to_gemini(self) -> None:
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import ExtractionInput

        ollama = _make_extraction_client(fail=True)
        gemini = _make_extraction_client()
        client = FallbackChainClient(
            ollama_extraction=ollama,
            gemini_extraction=gemini,
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = ExtractionInput(prompt="p", context="c", output_schema={}, model_id="m")
        result = asyncio.get_event_loop().run_until_complete(client.extract(inp))
        assert result is not None
        gemini.extract.assert_awaited_once()


class TestFallbackChainLlmLogging:
    def test_llm_usage_log_written_on_success(self) -> None:
        """Success → usage_log_repo.insert() called once."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import EmbeddingInput

        ollama = _make_embedding_client()
        usage_repo = AsyncMock()
        usage_repo.insert = AsyncMock(return_value=uuid4())

        client = FallbackChainClient(
            ollama_embedding=ollama,
            usage_log_repo=usage_repo,
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = EmbeddingInput(text="hello", model_id="nomic")
        asyncio.get_event_loop().run_until_complete(client.embed([inp]))
        usage_repo.insert.assert_awaited_once()

    def test_llm_usage_log_written_on_failure(self) -> None:
        """Failure → usage logged with success=False."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import EmbeddingInput

        ollama = _make_embedding_client(fail=True)
        usage_repo = AsyncMock()
        usage_repo.insert = AsyncMock(return_value=uuid4())

        client = FallbackChainClient(
            ollama_embedding=ollama,
            usage_log_repo=usage_repo,
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = EmbeddingInput(text="hello", model_id="nomic")
        asyncio.get_event_loop().run_until_complete(client.embed([inp]))
        # Should log with success=False
        call_kwargs = usage_repo.insert.call_args.kwargs
        assert call_kwargs["success"] is False
