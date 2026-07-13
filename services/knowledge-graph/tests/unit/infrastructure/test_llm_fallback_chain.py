"""Unit tests for FallbackChainClient (T-D-3-09)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

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
            return_value=ExtractionOutput(result={"summary": "ok"}, raw_response="ok", model_id="test"),
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

        result = asyncio.run(client.embed([]))
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

        result = asyncio.run(client.embed([]))
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

        result = asyncio.run(client.embed([]))
        assert result is None

    def test_no_clients_returns_none(self) -> None:
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

        client = FallbackChainClient(retry_delays_ollama=(), retry_delays_gemini=())
        result = asyncio.run(client.embed([]))
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
        result = asyncio.run(client.extract(inp))
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
        result = asyncio.run(client.extract(inp))
        assert result is not None
        gemini.extract.assert_awaited_once()


class TestFallbackChainLlmLogging:
    def test_llm_usage_log_written_on_success(self) -> None:
        """Success → usage_logger.log() called once (PLAN-0033 T-D-1-01: insert→log rename)."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import EmbeddingInput

        ollama = _make_embedding_client()
        # Duck-typed mock satisfying LlmUsageLogProtocol (has async .log())
        usage_logger = AsyncMock()
        usage_logger.log = AsyncMock(return_value=None)

        client = FallbackChainClient(
            ollama_embedding=ollama,
            usage_logger=usage_logger,
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = EmbeddingInput(text="hello", model_id="nomic")
        asyncio.run(client.embed([inp]))
        usage_logger.log.assert_awaited_once()

    def test_llm_usage_log_written_on_failure(self) -> None:
        """Failure → usage logged with success=False (PLAN-0033 T-D-1-01)."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import EmbeddingInput

        ollama = _make_embedding_client(fail=True)
        usage_logger = AsyncMock()
        usage_logger.log = AsyncMock(return_value=None)

        client = FallbackChainClient(
            ollama_embedding=ollama,
            usage_logger=usage_logger,
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = EmbeddingInput(text="hello", model_id="nomic")
        asyncio.run(client.embed([inp]))
        # Should log with success=False
        call_kwargs = usage_logger.log.call_args.kwargs
        assert call_kwargs["success"] is False


class TestFallbackChainDeepInfraExtraction:
    """Tests for DeepInfra primary extraction slot (PLAN-0061 T-C-1)."""

    def test_deepinfra_called_first_when_set(self) -> None:
        """DeepInfra is tried before Ollama when deepinfra_extraction is set."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import ExtractionInput

        deepinfra = _make_extraction_client()
        ollama = _make_extraction_client()
        client = FallbackChainClient(
            deepinfra_extraction=deepinfra,
            ollama_extraction=ollama,
            retry_delays_deepinfra=(),
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = ExtractionInput(prompt="p", context="c", output_schema={}, model_id="m")
        result = asyncio.run(client.extract(inp))
        assert result is not None
        deepinfra.extract.assert_awaited_once()
        ollama.extract.assert_not_awaited()

    def test_falls_back_to_ollama_when_deepinfra_fails(self) -> None:
        """DeepInfra failure → Ollama is called."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import ExtractionInput

        deepinfra = _make_extraction_client(fail=True)
        ollama = _make_extraction_client()
        client = FallbackChainClient(
            deepinfra_extraction=deepinfra,
            ollama_extraction=ollama,
            retry_delays_deepinfra=(),
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = ExtractionInput(prompt="p", context="c", output_schema={}, model_id="m")
        result = asyncio.run(client.extract(inp))
        assert result is not None
        ollama.extract.assert_awaited_once()

    def test_falls_back_to_gemini_when_deepinfra_and_ollama_fail(self) -> None:
        """DeepInfra + Ollama both fail → Gemini is called."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import ExtractionInput

        deepinfra = _make_extraction_client(fail=True)
        ollama = _make_extraction_client(fail=True)
        gemini = _make_extraction_client()
        client = FallbackChainClient(
            deepinfra_extraction=deepinfra,
            ollama_extraction=ollama,
            gemini_extraction=gemini,
            retry_delays_deepinfra=(),
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = ExtractionInput(prompt="p", context="c", output_schema={}, model_id="m")
        result = asyncio.run(client.extract(inp))
        assert result is not None
        gemini.extract.assert_awaited_once()

    def test_deepinfra_cost_logged(self) -> None:
        """Successful DeepInfra call logs a non-zero estimated_cost_usd.

        PLAN-0117 W3: cost now comes from the unified ``resolve_cost`` matrix
        (R13 — no local char-count heuristic), so the model_id must be a priced
        one for the matrix path to yield > 0. cost_source is 'pricematrix' when
        the client does not surface a provider cost.
        """
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import ExtractionInput

        deepinfra = _make_extraction_client()
        # A priced DeepInfra model so the matrix fallback returns a non-zero cost.
        deepinfra.model_id = "Qwen/Qwen3-235B-A22B-Instruct-2507"
        usage_logger = AsyncMock()
        usage_logger.log = AsyncMock(return_value=None)
        client = FallbackChainClient(
            deepinfra_extraction=deepinfra,
            usage_logger=usage_logger,
            retry_delays_deepinfra=(),
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        # Prompt long enough that cost > 0
        inp = ExtractionInput(
            prompt="extract financial events from this document " * 100,
            context="Apple reported record revenue of $120 billion in Q4 2025.",
            output_schema={},
            model_id="m",
        )
        asyncio.run(client.extract(inp))
        call_kwargs = usage_logger.log.call_args.kwargs
        assert call_kwargs["estimated_cost_usd"] > 0.0
        assert call_kwargs["provider"] == "deepinfra"
        assert call_kwargs["cost_source"] == "pricematrix"

    def test_deepinfra_provider_cost_preferred(self) -> None:
        """PLAN-0117 W3/FR-1: ExtractionOutput.provider_cost_usd → cost_source='provider'."""
        from decimal import Decimal

        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import ExtractionInput, ExtractionOutput

        deepinfra = AsyncMock()
        deepinfra.model_id = "openai/gpt-oss-120b"
        deepinfra.extract = AsyncMock(
            return_value=ExtractionOutput(
                result={"summary": "ok"},
                raw_response="ok",
                model_id="openai/gpt-oss-120b",
                provider_cost_usd=Decimal("0.00000041"),
            ),
        )
        usage_logger = AsyncMock()
        usage_logger.log = AsyncMock(return_value=None)
        client = FallbackChainClient(
            deepinfra_extraction=deepinfra,
            usage_logger=usage_logger,
            retry_delays_deepinfra=(),
        )
        inp = ExtractionInput(prompt="p", context="c", output_schema={}, model_id="m")
        asyncio.run(client.extract(inp))
        call_kwargs = usage_logger.log.call_args.kwargs
        assert call_kwargs["cost_source"] == "provider"
        assert call_kwargs["estimated_cost_usd"] == pytest.approx(4.1e-07)

    def test_ollama_extraction_is_local(self) -> None:
        """PLAN-0117 W3: Ollama-served extraction → cost_source='local', $0."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import ExtractionInput

        ollama = _make_extraction_client()  # model_id="test-model", provider ollama
        usage_logger = AsyncMock()
        usage_logger.log = AsyncMock(return_value=None)
        client = FallbackChainClient(
            ollama_extraction=ollama,
            usage_logger=usage_logger,
            retry_delays_ollama=(),
        )
        inp = ExtractionInput(prompt="p " * 50, context="c", output_schema={}, model_id="m")
        asyncio.run(client.extract(inp))
        call_kwargs = usage_logger.log.call_args.kwargs
        assert call_kwargs["cost_source"] == "local"
        assert call_kwargs["estimated_cost_usd"] == 0.0

    def test_no_deepinfra_falls_through_to_ollama(self) -> None:
        """When deepinfra_extraction=None, Ollama is called directly (backward-compat)."""
        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from ml_clients.dataclasses import ExtractionInput

        ollama = _make_extraction_client()
        client = FallbackChainClient(
            ollama_extraction=ollama,
            retry_delays_deepinfra=(),
            retry_delays_ollama=(),
            retry_delays_gemini=(),
        )
        inp = ExtractionInput(prompt="p", context="c", output_schema={}, model_id="m")
        result = asyncio.run(client.extract(inp))
        assert result is not None
        ollama.extract.assert_awaited_once()
