"""Adapter unit tests — all external calls are mocked."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ml_clients.dataclasses import (
    EmbeddingInput,
    ExtractionInput,
    NERInput,
)
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    import asyncio

# ── Helpers ───────────────────────────────────────────────────────────────────


def _extraction_input() -> ExtractionInput:
    return ExtractionInput(
        prompt="Extract entities as JSON",
        context="Apple Inc. reported earnings.",
        output_schema={"type": "object"},
        model_id="qwen2.5:7b-instruct",
    )


# ── OllamaEmbeddingAdapter ────────────────────────────────────────────────────


class TestOllamaEmbeddingAdapter:
    @pytest.fixture
    def adapter(self, semaphore: asyncio.Semaphore):  # type: ignore[no-untyped-def]
        from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter

        return OllamaEmbeddingAdapter(
            base_url="http://ollama:11434",
            model_id="bge-large-en-v1.5",
            semaphore=semaphore,
        )

    @pytest.fixture
    def inputs(self) -> list[EmbeddingInput]:
        return [EmbeddingInput(text="Apple Inc.", model_id="bge-large-en-v1.5")]

    async def test_timeout_raises_retryable(
        self,
        adapter,
        inputs: list[EmbeddingInput],  # type: ignore[no-untyped-def]
    ) -> None:
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            with pytest.raises(RetryableError, match="timeout"):
                await adapter.embed(inputs)

    async def test_server_error_raises_retryable(
        self,
        adapter,
        inputs: list[EmbeddingInput],  # type: ignore[no-untyped-def]
    ) -> None:
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err_resp = MagicMock(status_code=503)
            mock_client.post.side_effect = httpx.HTTPStatusError(message="503", request=MagicMock(), response=err_resp)
            with pytest.raises(RetryableError, match="5xx"):
                await adapter.embed(inputs)

    async def test_client_error_raises_fatal(
        self,
        adapter,
        inputs: list[EmbeddingInput],  # type: ignore[no-untyped-def]
    ) -> None:
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err_resp = MagicMock(status_code=400)
            mock_client.post.side_effect = httpx.HTTPStatusError(message="400", request=MagicMock(), response=err_resp)
            with pytest.raises(FatalError, match="4xx"):
                await adapter.embed(inputs)

    async def test_valid_response_returns_embedding_output(
        self,
        adapter,
        inputs: list[EmbeddingInput],  # type: ignore[no-untyped-def]
    ) -> None:
        embedding = [0.1] * 1024
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"embedding": embedding}
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            results = await adapter.embed(inputs)
        assert len(results) == 1
        assert results[0].dimension == 1024
        assert len(results[0].embedding) == 1024

    async def test_wrong_dimension_raises_fatal(
        self,
        adapter,
        inputs: list[EmbeddingInput],  # type: ignore[no-untyped-def]
    ) -> None:
        embedding = [0.1] * 512  # wrong dimension
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"embedding": embedding}
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            with pytest.raises(FatalError, match="dimension"):
                await adapter.embed(inputs)

    async def test_instruction_prefix_prepended(
        self,
        adapter,  # type: ignore[no-untyped-def]
    ) -> None:
        """Instruction prefix is concatenated with the text before sending."""
        inputs = [
            EmbeddingInput(
                text="Apple Inc.",
                model_id="bge-large-en-v1.5",
                instruction_prefix="Represent:",
            )
        ]
        embedding = [0.1] * 1024
        captured: list[dict] = []  # type: ignore[type-arg]

        async def fake_post(url: str, json: dict, **kwargs) -> MagicMock:  # type: ignore[type-arg]
            captured.append(json)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"embedding": embedding}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = fake_post
            await adapter.embed(inputs)

        assert captured[0]["prompt"] == "Represent: Apple Inc."


# ── OllamaExtractionAdapter ───────────────────────────────────────────────────


class TestOllamaExtractionAdapter:
    @pytest.fixture
    def adapter(self, semaphore: asyncio.Semaphore):  # type: ignore[no-untyped-def]
        from ml_clients.adapters.ollama_extraction import OllamaExtractionAdapter

        return OllamaExtractionAdapter(
            base_url="http://ollama:11434",
            model_id="qwen2.5:7b-instruct",
            semaphore=semaphore,
        )

    async def test_malformed_json_raises_fatal(self, adapter) -> None:  # type: ignore[no-untyped-def]
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"message": {"content": "not valid json {{{"}}
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            with pytest.raises(FatalError, match="malformed"):
                await adapter.extract(_extraction_input())

    async def test_valid_json_returns_extraction_output(self, adapter) -> None:  # type: ignore[no-untyped-def]
        payload = {"entities": ["Apple Inc."]}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"message": {"content": json.dumps(payload)}}
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            result = await adapter.extract(_extraction_input())
        assert result.result == payload
        assert result.model_id == "qwen2.5:7b-instruct"

    async def test_timeout_raises_retryable(self, adapter) -> None:  # type: ignore[no-untyped-def]
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            with pytest.raises(RetryableError, match="timeout"):
                await adapter.extract(_extraction_input())

    async def test_5xx_raises_retryable(self, adapter) -> None:  # type: ignore[no-untyped-def]
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = httpx.HTTPStatusError(
                message="500", request=MagicMock(), response=MagicMock(status_code=500)
            )
            with pytest.raises(RetryableError, match="5xx"):
                await adapter.extract(_extraction_input())


# ── GLiNERLocalAdapter ────────────────────────────────────────────────────────


class TestGLiNERLocalAdapter:
    @pytest.fixture
    def adapter(self, semaphore: asyncio.Semaphore):  # type: ignore[no-untyped-def]
        from ml_clients.adapters.gliner_local import GLiNERLocalAdapter

        return GLiNERLocalAdapter(model_path="urchade/gliner_large-v2.1", semaphore=semaphore)

    async def test_memory_error_raises_retryable(self, adapter) -> None:  # type: ignore[no-untyped-def]
        mock_model = MagicMock()
        mock_model.predict_entities.side_effect = MemoryError("OOM")
        adapter._model = mock_model

        with pytest.raises(RetryableError, match="transient"):
            await adapter.extract_entities(NERInput(text="Apple", entity_classes=["ORG"]))

    async def test_runtime_error_raises_retryable(self, adapter) -> None:  # type: ignore[no-untyped-def]
        mock_model = MagicMock()
        mock_model.predict_entities.side_effect = RuntimeError("CUDA OOM")
        adapter._model = mock_model

        with pytest.raises(RetryableError, match="transient"):
            await adapter.extract_entities(NERInput(text="Apple", entity_classes=["ORG"]))

    async def test_value_error_raises_fatal(self, adapter) -> None:  # type: ignore[no-untyped-def]
        mock_model = MagicMock()
        mock_model.predict_entities.side_effect = ValueError("invalid input")
        adapter._model = mock_model

        with pytest.raises(FatalError, match="input error"):
            await adapter.extract_entities(NERInput(text="Apple", entity_classes=["ORG"]))

    async def test_valid_entities_returned(self, adapter) -> None:  # type: ignore[no-untyped-def]
        raw = [{"text": "Apple Inc.", "label": "ORG", "start": 0, "end": 10, "score": 0.95}]
        mock_model = MagicMock()
        mock_model.predict_entities.return_value = raw
        adapter._model = mock_model

        result = await adapter.extract_entities(NERInput(text="Apple Inc. reported earnings", entity_classes=["ORG"]))
        assert len(result.mentions) == 1
        assert result.mentions[0].label == "ORG"
        assert result.mentions[0].score == 0.95

    async def test_nms_removes_overlapping_spans(self, adapter) -> None:  # type: ignore[no-untyped-def]
        """Higher-scored span is kept; overlapping lower-scored span is discarded.

        Spans [0,10] and [0,8]: intersection=8, union=10, IoU=0.8 > 0.5 → removed.
        """
        raw = [
            {"text": "Apple Inc.", "label": "ORG", "start": 0, "end": 10, "score": 0.95},
            {"text": "Apple Inc", "label": "ORG", "start": 0, "end": 8, "score": 0.80},
        ]
        mock_model = MagicMock()
        mock_model.predict_entities.return_value = raw
        adapter._model = mock_model

        result = await adapter.extract_entities(NERInput(text="Apple Inc. reported", entity_classes=["ORG"]))
        assert len(result.mentions) == 1
        assert result.mentions[0].text == "Apple Inc."

    async def test_missing_gliner_package_raises_fatal(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters import gliner_local

        original = gliner_local._GLINER_AVAILABLE
        try:
            gliner_local._GLINER_AVAILABLE = False
            from ml_clients.adapters.gliner_local import GLiNERLocalAdapter

            adapter = GLiNERLocalAdapter(model_path="some/model", semaphore=semaphore)
            with pytest.raises(FatalError, match="gliner package not installed"):
                await adapter.extract_entities(NERInput(text="test", entity_classes=["ORG"]))
        finally:
            gliner_local._GLINER_AVAILABLE = original


# ── GLiNERHTTPAdapter ─────────────────────────────────────────────────────────


class TestGLiNERHTTPAdapter:
    """Covers the containerised-GLiNER HTTP client: timeout default/override and
    the timeout→RetryableError mapping (regression for the self-inflicted-looking
    but actually capacity-driven 'GLiNER server timeout' storm)."""

    def test_default_timeout_is_240s(self, semaphore: asyncio.Semaphore) -> None:
        # The default must comfortably exceed the GLiNER server's batched tail
        # latency (a 16-text /ner/batch call measured ~79s under concurrent
        # CPU-bound load; multi-section docs issue several such batches) so a
        # merely-slow server (returning 200s) is not retried as a failure.
        from ml_clients.adapters.gliner_http import GLiNERHTTPAdapter

        adapter = GLiNERHTTPAdapter(base_url="http://gliner-server:8080", semaphore=semaphore)
        assert adapter._timeout == 240.0

    def test_timeout_is_overridable(self, semaphore: asyncio.Semaphore) -> None:
        # Ops must be able to tune the timeout (env-backed setting in the
        # nlp-pipeline) without a code change.
        from ml_clients.adapters.gliner_http import GLiNERHTTPAdapter

        adapter = GLiNERHTTPAdapter(
            base_url="http://gliner-server:8080",
            semaphore=semaphore,
            timeout_seconds=200.0,
        )
        assert adapter._timeout == 200.0

    async def test_timeout_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        import httpx
        from ml_clients.adapters.gliner_http import GLiNERHTTPAdapter

        adapter = GLiNERHTTPAdapter(base_url="http://gliner-server:8080", semaphore=semaphore)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = httpx.TimeoutException("read timeout")
            with pytest.raises(RetryableError, match="GLiNER server timeout"):
                await adapter.extract_entities(NERInput(text="Apple Inc.", entity_classes=["company"]))


# ── AnthropicExtractionAdapter ────────────────────────────────────────────────


class TestAnthropicExtractionAdapter:
    async def test_missing_package_raises_fatal(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.anthropic_extraction import AnthropicExtractionAdapter

        adapter = AnthropicExtractionAdapter(api_key="key", semaphore=semaphore)
        with (
            patch.dict(sys.modules, {"anthropic": None}),
            pytest.raises(FatalError, match="anthropic package not installed"),
        ):
            await adapter.extract(_extraction_input())

    async def test_rate_limit_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.anthropic_extraction import AnthropicExtractionAdapter

        adapter = AnthropicExtractionAdapter(api_key="key", semaphore=semaphore)

        mock_anthropic = MagicMock()

        class _AnthropicBaseError(Exception):
            pass

        class FakeRateLimitError(_AnthropicBaseError):
            pass

        class FakeConnectionError(_AnthropicBaseError):
            pass

        class FakeBadRequestError(_AnthropicBaseError):
            pass

        mock_anthropic.RateLimitError = FakeRateLimitError
        mock_anthropic.APIConnectionError = FakeConnectionError
        mock_anthropic.BadRequestError = FakeBadRequestError

        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = FakeRateLimitError("rate limited")
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        with (
            patch.dict("sys.modules", {"anthropic": mock_anthropic}),
            pytest.raises(RetryableError, match="rate limit"),
        ):
            await adapter.extract(_extraction_input())

    async def test_connection_error_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.anthropic_extraction import AnthropicExtractionAdapter

        adapter = AnthropicExtractionAdapter(api_key="key", semaphore=semaphore)

        mock_anthropic = MagicMock()

        class _AnthropicBaseError(Exception):
            pass

        class FakeRateLimitError(_AnthropicBaseError):
            pass

        class FakeConnectionError(_AnthropicBaseError):
            pass

        class FakeBadRequestError(_AnthropicBaseError):
            pass

        mock_anthropic.RateLimitError = FakeRateLimitError
        mock_anthropic.APIConnectionError = FakeConnectionError
        mock_anthropic.BadRequestError = FakeBadRequestError

        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = FakeConnectionError("connection failed")
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        with (
            patch.dict("sys.modules", {"anthropic": mock_anthropic}),
            pytest.raises(RetryableError, match="connection"),
        ):
            await adapter.extract(_extraction_input())

    async def test_bad_request_raises_fatal(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.anthropic_extraction import AnthropicExtractionAdapter

        adapter = AnthropicExtractionAdapter(api_key="key", semaphore=semaphore)

        mock_anthropic = MagicMock()

        class _AnthropicBaseError(Exception):
            pass

        class FakeRateLimitError(_AnthropicBaseError):
            pass

        class FakeConnectionError(_AnthropicBaseError):
            pass

        class FakeBadRequestError(_AnthropicBaseError):
            pass

        mock_anthropic.RateLimitError = FakeRateLimitError
        mock_anthropic.APIConnectionError = FakeConnectionError
        mock_anthropic.BadRequestError = FakeBadRequestError

        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = FakeBadRequestError("bad request")
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}), pytest.raises(FatalError, match="bad request"):
            await adapter.extract(_extraction_input())

    async def test_valid_json_response_returns_output(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.anthropic_extraction import AnthropicExtractionAdapter

        adapter = AnthropicExtractionAdapter(api_key="key", semaphore=semaphore)

        mock_anthropic = MagicMock()
        mock_anthropic.RateLimitError = Exception
        mock_anthropic.APIConnectionError = Exception
        mock_anthropic.BadRequestError = Exception

        payload = {"company": "Apple Inc."}
        mock_content = MagicMock()
        mock_content.text = json.dumps(payload)
        mock_response = MagicMock()
        mock_response.content = [mock_content]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = await adapter.extract(_extraction_input())

        assert result.result == payload
        assert result.model_id == "claude-sonnet-4-6"


# ── GeminiExtractionAdapter ───────────────────────────────────────────────────


class TestGeminiExtractionAdapter:
    async def test_rate_limit_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.gemini_extraction import GeminiExtractionAdapter

        adapter = GeminiExtractionAdapter(api_key="key", semaphore=semaphore)

        mock_genai = MagicMock()

        class FakeResourceExhaustedError(Exception):
            pass

        FakeResourceExhaustedError.__name__ = "ResourceExhausted"

        mock_models_aio = AsyncMock()
        mock_models_aio.generate_content = AsyncMock(side_effect=FakeResourceExhaustedError("quota"))
        mock_client = MagicMock()
        mock_client.aio.models = mock_models_aio
        mock_genai.Client.return_value = mock_client

        mock_google = MagicMock()
        mock_google.genai = mock_genai

        with (
            patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}),
            pytest.raises(RetryableError),
        ):
            await adapter.extract(_extraction_input())

    async def test_malformed_output_raises_fatal(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.gemini_extraction import GeminiExtractionAdapter

        adapter = GeminiExtractionAdapter(api_key="key", semaphore=semaphore)

        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "not valid json {{{"

        mock_models_aio = AsyncMock()
        mock_models_aio.generate_content = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.aio.models = mock_models_aio
        mock_genai.Client.return_value = mock_client

        mock_google = MagicMock()
        mock_google.genai = mock_genai

        with (
            patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}),
            pytest.raises(FatalError, match="malformed"),
        ):
            await adapter.extract(_extraction_input())

    async def test_valid_response_returns_output(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.gemini_extraction import GeminiExtractionAdapter

        adapter = GeminiExtractionAdapter(api_key="key", semaphore=semaphore)

        payload = {"extracted": "data"}
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(payload)

        mock_models_aio = AsyncMock()
        mock_models_aio.generate_content = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.aio.models = mock_models_aio
        mock_genai.Client.return_value = mock_client

        mock_google = MagicMock()
        mock_google.genai = mock_genai

        with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
            result = await adapter.extract(_extraction_input())

        assert result.result == payload

    async def test_missing_package_raises_fatal(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.gemini_extraction import GeminiExtractionAdapter

        adapter = GeminiExtractionAdapter(api_key="key", semaphore=semaphore)
        with patch.dict(sys.modules, {"google": None, "google.genai": None}), pytest.raises((FatalError, ImportError)):
            await adapter.extract(_extraction_input())


# ── ChatGPTExtractionAdapter ──────────────────────────────────────────────────


class TestChatGPTExtractionAdapter:
    async def test_rate_limit_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.chatgpt_extraction import ChatGPTExtractionAdapter

        adapter = ChatGPTExtractionAdapter(api_key="key", semaphore=semaphore)

        mock_openai = MagicMock()

        class _OpenAIBaseError(Exception):
            pass

        class FakeRateLimitError(_OpenAIBaseError):
            pass

        class FakeConnectionError(_OpenAIBaseError):
            pass

        class FakeTimeoutError(_OpenAIBaseError):
            pass

        class FakeStatusError(_OpenAIBaseError):
            status_code = 400

        mock_openai.RateLimitError = FakeRateLimitError
        mock_openai.APIConnectionError = FakeConnectionError
        mock_openai.APITimeoutError = FakeTimeoutError
        mock_openai.APIStatusError = FakeStatusError

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = FakeRateLimitError("429")
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}), pytest.raises(RetryableError, match="rate limit"):
            await adapter.extract(_extraction_input())

    async def test_connection_error_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.chatgpt_extraction import ChatGPTExtractionAdapter

        adapter = ChatGPTExtractionAdapter(api_key="key", semaphore=semaphore)

        mock_openai = MagicMock()

        class _OpenAIBaseError(Exception):
            pass

        class FakeRateLimitError(_OpenAIBaseError):
            pass

        class FakeConnectionError(_OpenAIBaseError):
            pass

        class FakeTimeoutError(_OpenAIBaseError):
            pass

        class FakeStatusError(_OpenAIBaseError):
            status_code = 400

        mock_openai.RateLimitError = FakeRateLimitError
        mock_openai.APIConnectionError = FakeConnectionError
        mock_openai.APITimeoutError = FakeTimeoutError
        mock_openai.APIStatusError = FakeStatusError

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = FakeConnectionError("network")
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}), pytest.raises(RetryableError, match="connection"):
            await adapter.extract(_extraction_input())

    async def test_4xx_raises_fatal(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.chatgpt_extraction import ChatGPTExtractionAdapter

        adapter = ChatGPTExtractionAdapter(api_key="key", semaphore=semaphore)

        mock_openai = MagicMock()

        class _OpenAIBaseError(Exception):
            pass

        class FakeRateLimitError(_OpenAIBaseError):
            pass

        class FakeConnectionError(_OpenAIBaseError):
            pass

        class FakeTimeoutError(_OpenAIBaseError):
            pass

        class FakeStatusError(_OpenAIBaseError):
            status_code = 422

        mock_openai.RateLimitError = FakeRateLimitError
        mock_openai.APIConnectionError = FakeConnectionError
        mock_openai.APITimeoutError = FakeTimeoutError
        mock_openai.APIStatusError = FakeStatusError

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = FakeStatusError("unprocessable")
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}), pytest.raises(FatalError, match="4xx"):
            await adapter.extract(_extraction_input())

    async def test_valid_response_returns_output(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.chatgpt_extraction import ChatGPTExtractionAdapter

        adapter = ChatGPTExtractionAdapter(api_key="key", semaphore=semaphore)

        payload = {"result": "ok"}
        mock_openai = MagicMock()
        mock_openai.RateLimitError = Exception
        mock_openai.APIConnectionError = Exception
        mock_openai.APITimeoutError = Exception
        mock_openai.APIStatusError = Exception

        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(payload)
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}):
            result = await adapter.extract(_extraction_input())

        assert result.result == payload


# ── DeepSeekExtractionAdapter ─────────────────────────────────────────────────


class TestDeepSeekExtractionAdapter:
    async def test_timeout_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

        mock_openai = MagicMock()

        class _OpenAIBaseError(Exception):
            pass

        class FakeRateLimitError(_OpenAIBaseError):
            pass

        class FakeConnectionError(_OpenAIBaseError):
            pass

        class FakeTimeoutError(_OpenAIBaseError):
            pass

        class FakeStatusError(_OpenAIBaseError):
            status_code = 400

        mock_openai.RateLimitError = FakeRateLimitError
        mock_openai.APIConnectionError = FakeConnectionError
        mock_openai.APITimeoutError = FakeTimeoutError
        mock_openai.APIStatusError = FakeStatusError

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = FakeTimeoutError("timeout")
        mock_openai.AsyncOpenAI.return_value = mock_client

        # Adapter must be created inside patch.dict: __init__ does `import openai`
        # eagerly, binding self._openai and self._client to the real module. Creating
        # it outside the mock context means the real cached_property fires during
        # extract() while sys.modules["openai"] is the MagicMock — raising
        # ModuleNotFoundError("'openai' is not a package") before the fake error fires.
        with patch.dict("sys.modules", {"openai": mock_openai}), pytest.raises(RetryableError, match="timeout"):
            adapter = DeepSeekExtractionAdapter(api_key="key", semaphore=semaphore)
            await adapter.extract(_extraction_input())

    async def test_rate_limit_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

        mock_openai = MagicMock()

        class _OpenAIBaseError(Exception):
            pass

        class FakeRateLimitError(_OpenAIBaseError):
            pass

        class FakeConnectionError(_OpenAIBaseError):
            pass

        class FakeTimeoutError(_OpenAIBaseError):
            pass

        class FakeStatusError(_OpenAIBaseError):
            status_code = 400

        mock_openai.RateLimitError = FakeRateLimitError
        mock_openai.APIConnectionError = FakeConnectionError
        mock_openai.APITimeoutError = FakeTimeoutError
        mock_openai.APIStatusError = FakeStatusError

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = FakeRateLimitError("429")
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}), pytest.raises(RetryableError, match="429"):
            adapter = DeepSeekExtractionAdapter(api_key="key", semaphore=semaphore)
            await adapter.extract(_extraction_input())

    async def test_4xx_raises_fatal(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

        mock_openai = MagicMock()

        class _OpenAIBaseError(Exception):
            pass

        class FakeRateLimitError(_OpenAIBaseError):
            pass

        class FakeConnectionError(_OpenAIBaseError):
            pass

        class FakeTimeoutError(_OpenAIBaseError):
            pass

        class FakeStatusError(_OpenAIBaseError):
            status_code = 400

        mock_openai.RateLimitError = FakeRateLimitError
        mock_openai.APIConnectionError = FakeConnectionError
        mock_openai.APITimeoutError = FakeTimeoutError
        mock_openai.APIStatusError = FakeStatusError

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = FakeStatusError("bad request")
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}), pytest.raises(FatalError, match="4xx"):
            adapter = DeepSeekExtractionAdapter(api_key="key", semaphore=semaphore)
            await adapter.extract(_extraction_input())

    async def test_valid_response_with_deepseek_base_url(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

        payload = {"extracted": "value"}
        mock_openai = MagicMock()
        mock_openai.RateLimitError = Exception
        mock_openai.APIConnectionError = Exception
        mock_openai.APITimeoutError = Exception
        mock_openai.APIStatusError = Exception

        captured_kwargs: list[dict] = []  # type: ignore[type-arg]

        def fake_async_openai(**kwargs: object) -> AsyncMock:
            captured_kwargs.append(dict(kwargs))
            mock_client = AsyncMock()
            mock_choice = MagicMock()
            mock_choice.message.content = json.dumps(payload)
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            return mock_client

        mock_openai.AsyncOpenAI.side_effect = fake_async_openai

        with patch.dict("sys.modules", {"openai": mock_openai}):
            adapter = DeepSeekExtractionAdapter(
                api_key="key",
                base_url="https://api.deepseek.com/v1",
                semaphore=semaphore,
            )
            result = await adapter.extract(_extraction_input())

        assert result.result == payload
        assert captured_kwargs[0]["base_url"] == "https://api.deepseek.com/v1"


# ── DeepInfraDescriptionAdapter ───────────────────────────────────────────────


def _make_openai_mock(content: str = "Apple Inc. is a tech company.") -> MagicMock:
    """Build a minimal openai module mock that returns *content* as the completion."""
    mock_openai = MagicMock()
    mock_openai.RateLimitError = type("RateLimitError", (Exception,), {})
    mock_openai.APIConnectionError = type("APIConnectionError", (Exception,), {})
    mock_openai.APITimeoutError = type("APITimeoutError", (Exception,), {})
    mock_openai.APIStatusError = type("APIStatusError", (Exception,), {"status_code": 400})
    mock_openai.Timeout = MagicMock(return_value=MagicMock())

    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 50
    mock_response.usage.completion_tokens = 30

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.close = AsyncMock()
    mock_openai.AsyncOpenAI.return_value = mock_client

    return mock_openai


class TestDeepInfraDescriptionAdapter:
    """Tests for DeepInfraDescriptionAdapter (Qwen3 primary + fallback, think-block stripping)."""

    async def test_primary_model_succeeds_returns_description(self, semaphore: asyncio.Semaphore) -> None:
        """Happy path: primary model returns description text."""
        mock_openai = _make_openai_mock("Apple Inc. is a leading technology company.")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            from ml_clients.adapters.deepinfra_description import DeepInfraDescriptionAdapter

            adapter = DeepInfraDescriptionAdapter(api_key="key", semaphore=semaphore)
            result = await adapter.generate_description(
                entity_id="ent-1",
                canonical_name="Apple Inc.",
                entity_type="company",
                context_hints={},
            )

        assert result == "Apple Inc. is a leading technology company."

    async def test_think_blocks_stripped_from_response(self, semaphore: asyncio.Semaphore) -> None:
        """Qwen3 <think>…</think> reasoning blocks are removed before returning."""
        content_with_think = "<think>Let me think...</think>Apple Inc. is a tech company."
        mock_openai = _make_openai_mock(content_with_think)

        with patch.dict("sys.modules", {"openai": mock_openai}):
            from ml_clients.adapters.deepinfra_description import DeepInfraDescriptionAdapter

            adapter = DeepInfraDescriptionAdapter(api_key="key", semaphore=semaphore)
            result = await adapter.generate_description(
                entity_id="ent-1",
                canonical_name="Apple Inc.",
                entity_type="company",
                context_hints={},
            )

        assert result == "Apple Inc. is a tech company."
        assert "<think>" not in (result or "")

    async def test_empty_after_think_stripping_returns_none(self, semaphore: asyncio.Semaphore) -> None:
        """If stripping think blocks yields empty string, returns None (no empty descriptions)."""
        mock_openai = _make_openai_mock("<think>all content is reasoning</think>")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            from ml_clients.adapters.deepinfra_description import DeepInfraDescriptionAdapter

            adapter = DeepInfraDescriptionAdapter(api_key="key", semaphore=semaphore)
            result = await adapter.generate_description(
                entity_id="ent-1",
                canonical_name="Apple Inc.",
                entity_type="company",
                context_hints={},
            )

        assert result is None

    async def test_primary_fails_fallback_succeeds(self, semaphore: asyncio.Semaphore) -> None:
        """When primary model fails, fallback model is tried and its result is returned."""
        mock_openai = MagicMock()
        mock_openai.RateLimitError = type("RateLimitError", (Exception,), {})
        mock_openai.APIConnectionError = type("APIConnectionError", (Exception,), {})
        mock_openai.APITimeoutError = type("APITimeoutError", (Exception,), {})
        mock_openai.APIStatusError = type("APIStatusError", (Exception,), {"status_code": 500})
        mock_openai.Timeout = MagicMock(return_value=MagicMock())

        call_count = 0

        async def _conditional_create(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise mock_openai.RateLimitError("rate limited")
            mock_choice = MagicMock()
            mock_choice.message.content = "Fallback description."
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]
            mock_response.usage.prompt_tokens = 40
            mock_response.usage.completion_tokens = 20
            return mock_response

        mock_client = AsyncMock()
        mock_client.chat.completions.create = _conditional_create
        mock_client.close = AsyncMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}):
            from ml_clients.adapters.deepinfra_description import DeepInfraDescriptionAdapter

            adapter = DeepInfraDescriptionAdapter(
                api_key="key",
                primary_model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
                fallback_model_id="Qwen/Qwen3-32B",
                semaphore=semaphore,
            )
            result = await adapter.generate_description(
                entity_id="ent-2",
                canonical_name="Tesla",
                entity_type="company",
                context_hints={},
            )

        assert result == "Fallback description."
        assert call_count == 2

    async def test_both_models_fail_returns_none(self, semaphore: asyncio.Semaphore) -> None:
        """When both primary and fallback fail, returns None."""
        mock_openai = MagicMock()
        mock_openai.RateLimitError = type("RateLimitError", (Exception,), {})
        mock_openai.APIConnectionError = type("APIConnectionError", (Exception,), {})
        mock_openai.APITimeoutError = type("APITimeoutError", (Exception,), {})
        mock_openai.APIStatusError = type("APIStatusError", (Exception,), {"status_code": 500})
        mock_openai.Timeout = MagicMock(return_value=MagicMock())

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_openai.APIConnectionError("network down"))
        mock_client.close = AsyncMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}):
            from ml_clients.adapters.deepinfra_description import DeepInfraDescriptionAdapter

            adapter = DeepInfraDescriptionAdapter(api_key="key", semaphore=semaphore)
            result = await adapter.generate_description(
                entity_id="ent-3",
                canonical_name="Nvidia",
                entity_type="company",
                context_hints={},
            )

        assert result is None

    async def test_cost_cap_exceeded_returns_none_without_api_call(self, semaphore: asyncio.Semaphore) -> None:
        """When monthly cost cap is exceeded, returns None without calling the API."""
        mock_openai = _make_openai_mock("Should not be called.")

        mock_cost_tracker = AsyncMock()
        # Simulate cap exceeded: incrbyfloat returns value >= cap_threshold
        mock_cost_tracker.incrbyfloat = AsyncMock(return_value=99.99)

        with patch.dict("sys.modules", {"openai": mock_openai}):
            from ml_clients.adapters.deepinfra_description import DeepInfraDescriptionAdapter

            adapter = DeepInfraDescriptionAdapter(
                api_key="key",
                semaphore=semaphore,
                cost_tracker=mock_cost_tracker,
                max_monthly_usd=10.0,
            )
            result = await adapter.generate_description(
                entity_id="ent-4",
                canonical_name="Google",
                entity_type="company",
                context_hints={},
            )

        assert result is None
        mock_openai.AsyncOpenAI.return_value.chat.completions.create.assert_not_called()

    async def test_context_hints_included_in_prompt(self, semaphore: asyncio.Semaphore) -> None:
        """Context hints are incorporated into the prompt sent to the model."""
        captured_prompts: list[str] = []

        mock_openai = MagicMock()
        mock_openai.RateLimitError = type("RateLimitError", (Exception,), {})
        mock_openai.APIConnectionError = type("APIConnectionError", (Exception,), {})
        mock_openai.APITimeoutError = type("APITimeoutError", (Exception,), {})
        mock_openai.APIStatusError = type("APIStatusError", (Exception,), {"status_code": 500})
        mock_openai.Timeout = MagicMock(return_value=MagicMock())

        async def _capture_create(**kwargs: object) -> MagicMock:
            messages = kwargs.get("messages", [])
            if len(messages) > 1:
                # messages[0] is the static system prompt; messages[1] is the user-turn
                # which contains the entity name, type, and context_hints.
                captured_prompts.append(messages[1]["content"])
            mock_choice = MagicMock()
            mock_choice.message.content = "Description with context."
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]
            mock_response.usage.prompt_tokens = 60
            mock_response.usage.completion_tokens = 25
            return mock_response

        mock_client = AsyncMock()
        mock_client.chat.completions.create = _capture_create
        mock_client.close = AsyncMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}):
            from ml_clients.adapters.deepinfra_description import DeepInfraDescriptionAdapter

            adapter = DeepInfraDescriptionAdapter(api_key="key", semaphore=semaphore)
            await adapter.generate_description(
                entity_id="ent-5",
                canonical_name="Apple Inc.",
                entity_type="company",
                context_hints={"sector": "Technology", "country": "US"},
            )

        assert len(captured_prompts) == 1
        assert "sector" in captured_prompts[0]
        assert "Technology" in captured_prompts[0]


# ── DeepInfraEmbeddingAdapter ─────────────────────────────────────────────────


def _make_deepinfra_embedding_response(embeddings: list[list[float]], *, status_code: int = 200) -> MagicMock:
    """Build a mock httpx response shaped like the DeepInfra OpenAI embeddings API."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [{"embedding": emb, "index": i} for i, emb in enumerate(embeddings)],
        "model": "BAAI/bge-large-en-v1.5",
        "object": "list",
    }
    return mock_resp


class TestDeepInfraEmbeddingAdapter:
    """Unit tests for DeepInfraEmbeddingAdapter (DEF-029)."""

    async def test_happy_path_returns_1024_dim_outputs(self) -> None:
        """Successful API call returns EmbeddingOutput with 1024-dim vector per input."""
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput

        inputs = [EmbeddingInput(text="Apple Inc. revenue Q3.", model_id="BAAI/bge-large-en-v1.5")]
        embedding = [0.1] * 1024

        mock_resp = _make_deepinfra_embedding_response([embedding])

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            results = await adapter.embed(inputs)

        assert len(results) == 1
        assert results[0].dimension == 1024
        assert len(results[0].embedding) == 1024
        assert results[0].model_id == "BAAI/bge-large-en-v1.5"

    async def test_empty_input_returns_empty_list(self) -> None:
        """embed([]) → [] without making any HTTP request."""
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter

        adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
        results = await adapter.embed([])
        assert results == []

    async def test_wrong_dimension_raises_fatal_error(self) -> None:
        """API returns wrong-dimension vector → FatalError with 'dimension' in message."""

        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import FatalError

        inputs = [EmbeddingInput(text="test text", model_id="BAAI/bge-large-en-v1.5")]
        wrong_dim_embedding = [0.1] * 512  # 512 instead of expected 1024

        mock_resp = _make_deepinfra_embedding_response([wrong_dim_embedding])

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            with pytest.raises(FatalError, match="dimension"):
                await adapter.embed(inputs)

    async def test_5xx_raises_retryable_error(self) -> None:
        """HTTP 5xx response → RetryableError (safe to retry)."""
        import httpx
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import RetryableError

        inputs = [EmbeddingInput(text="test text", model_id="BAAI/bge-large-en-v1.5")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err_resp = MagicMock(status_code=503)
            mock_client.post.side_effect = httpx.HTTPStatusError(
                message="503 Service Unavailable", request=MagicMock(), response=err_resp
            )

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            with pytest.raises(RetryableError, match="5xx"):
                await adapter.embed(inputs)

    async def test_4xx_raises_fatal_error(self) -> None:
        """HTTP 4xx response → FatalError (bad request, do not retry)."""
        import httpx
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import FatalError

        inputs = [EmbeddingInput(text="test text", model_id="BAAI/bge-large-en-v1.5")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err_resp = MagicMock(status_code=401)
            mock_client.post.side_effect = httpx.HTTPStatusError(
                message="401 Unauthorized", request=MagicMock(), response=err_resp
            )

            adapter = DeepInfraEmbeddingAdapter(api_key="bad-key")
            with pytest.raises(FatalError, match="4xx"):
                await adapter.embed(inputs)

    async def test_timeout_raises_retryable_error(self) -> None:
        """Network timeout → RetryableError."""
        import httpx
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import RetryableError

        inputs = [EmbeddingInput(text="test", model_id="BAAI/bge-large-en-v1.5")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = httpx.TimeoutException("read timeout")

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            with pytest.raises(RetryableError, match="timeout"):
                await adapter.embed(inputs)

    async def test_instruction_prefix_prepended_and_truncated(self) -> None:
        """Instruction prefix is prepended to the text and result is truncated to 1500 chars."""
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput

        long_text = "A" * 2000  # deliberately over 1500 chars
        inputs = [
            EmbeddingInput(
                text=long_text,
                model_id="BAAI/bge-large-en-v1.5",
                instruction_prefix="Represent this text:",
            )
        ]
        captured_json: list[dict] = []

        async def _fake_post(url: str, *, headers: dict, json: dict, **kwargs: object) -> MagicMock:
            captured_json.append(json)
            return _make_deepinfra_embedding_response([[0.1] * 1024])

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = _fake_post

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            await adapter.embed(inputs)

        assert len(captured_json) == 1
        sent_text = captured_json[0]["input"][0]
        # Prefix should be present, total length should not exceed 1500 chars
        assert sent_text.startswith("Represent this text:")
        assert len(sent_text) <= 1500

    async def test_result_count_mismatch_raises_fatal(self) -> None:
        """API returns fewer items than inputs → FatalError."""
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import FatalError

        # 2 inputs but mock only returns 1 embedding
        inputs = [
            EmbeddingInput(text="text 1", model_id="BAAI/bge-large-en-v1.5"),
            EmbeddingInput(text="text 2", model_id="BAAI/bge-large-en-v1.5"),
        ]
        mock_resp = _make_deepinfra_embedding_response([[0.1] * 1024])  # only 1 result

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            with pytest.raises(FatalError):
                await adapter.embed(inputs)

    async def test_bearer_auth_header_sent(self) -> None:
        """Authorization: Bearer <api_key> header is present in the request."""
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput

        inputs = [EmbeddingInput(text="hello", model_id="BAAI/bge-large-en-v1.5")]
        captured_headers: list[dict] = []

        async def _capture(url: str, *, headers: dict, json: dict, **kwargs: object) -> MagicMock:
            captured_headers.append(headers)
            return _make_deepinfra_embedding_response([[0.1] * 1024])

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = _capture

            adapter = DeepInfraEmbeddingAdapter(api_key="my-secret-deepinfra-key")
            await adapter.embed(inputs)

        assert len(captured_headers) == 1
        assert "Bearer my-secret-deepinfra-key" in captured_headers[0]["Authorization"]

    # ── LIB-005 / TASK-W4-03: 429 is RETRYABLE ───────────────────────────────
    # Previously DeepInfra 429 was caught by the generic 4xx branch and raised as
    # FatalError, which crashed the Kafka consumer instead of triggering a
    # back-off + retry. These tests pin the new behaviour: 429 must propagate as
    # ``RateLimitError`` (a subclass of ``RetryableError``) and the
    # ``Retry-After`` header must be parsed into ``exc.retry_after``.

    async def test_429_raises_retryable_rate_limit_error(self) -> None:
        """HTTP 429 → ``RateLimitError`` which IS a ``RetryableError``."""
        import httpx
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import FatalError, RateLimitError, RetryableError

        inputs = [EmbeddingInput(text="test text", model_id="BAAI/bge-large-en-v1.5")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            # 429 with NO Retry-After header → retry_after must be None
            err_resp = MagicMock(status_code=429, headers={})
            mock_client.post.side_effect = httpx.HTTPStatusError(
                message="429 Too Many Requests", request=MagicMock(), response=err_resp
            )

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            with pytest.raises(RateLimitError) as exc_info:
                await adapter.embed(inputs)

        # Must also be RetryableError (consumers catching RetryableError pick it up)
        assert isinstance(exc_info.value, RetryableError)
        # Must NOT be FatalError (would route to DLQ instead of back-off)
        assert not isinstance(exc_info.value, FatalError)
        # No header supplied → retry_after defaults to None
        assert exc_info.value.retry_after is None

    async def test_429_parses_retry_after_seconds_header(self) -> None:
        """``Retry-After: 5`` (integer seconds) → ``exc.retry_after == 5``."""
        import httpx
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import RateLimitError

        inputs = [EmbeddingInput(text="test text", model_id="BAAI/bge-large-en-v1.5")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err_resp = MagicMock(status_code=429, headers={"Retry-After": "5"})
            mock_client.post.side_effect = httpx.HTTPStatusError(
                message="429 Too Many Requests", request=MagicMock(), response=err_resp
            )

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            with pytest.raises(RateLimitError) as exc_info:
                await adapter.embed(inputs)

        assert exc_info.value.retry_after == 5

    async def test_429_missing_retry_after_defaults_to_none(self) -> None:
        """No ``Retry-After`` header → ``exc.retry_after is None`` (caller uses default back-off)."""
        import httpx
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import RateLimitError

        inputs = [EmbeddingInput(text="test text", model_id="BAAI/bge-large-en-v1.5")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            # Distinct from previous test: pass a non-empty headers dict that
            # simply lacks Retry-After, to prove the parser checks the key.
            err_resp = MagicMock(status_code=429, headers={"X-RateLimit-Limit": "1000"})
            mock_client.post.side_effect = httpx.HTTPStatusError(
                message="429 Too Many Requests", request=MagicMock(), response=err_resp
            )

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            with pytest.raises(RateLimitError) as exc_info:
                await adapter.embed(inputs)

        assert exc_info.value.retry_after is None

    async def test_5xx_still_raises_retryable_non_regression(self) -> None:
        """5xx must continue to raise RetryableError (NOT RateLimitError) after the 429 patch."""
        import httpx
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import RateLimitError, RetryableError

        inputs = [EmbeddingInput(text="test text", model_id="BAAI/bge-large-en-v1.5")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err_resp = MagicMock(status_code=503, headers={})
            mock_client.post.side_effect = httpx.HTTPStatusError(
                message="503 Service Unavailable", request=MagicMock(), response=err_resp
            )

            adapter = DeepInfraEmbeddingAdapter(api_key="test-key")
            with pytest.raises(RetryableError, match="5xx") as exc_info:
                await adapter.embed(inputs)

        # Must NOT be misclassified as a rate-limit error
        assert not isinstance(exc_info.value, RateLimitError)

    async def test_401_still_fatal_non_regression(self) -> None:
        """401 must continue to raise FatalError (auth bug, retrying won't help)."""
        import httpx
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
        from ml_clients.dataclasses import EmbeddingInput
        from ml_clients.errors import FatalError, RetryableError

        inputs = [EmbeddingInput(text="test text", model_id="BAAI/bge-large-en-v1.5")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            err_resp = MagicMock(status_code=401, headers={})
            mock_client.post.side_effect = httpx.HTTPStatusError(
                message="401 Unauthorized", request=MagicMock(), response=err_resp
            )

            adapter = DeepInfraEmbeddingAdapter(api_key="bad-key")
            with pytest.raises(FatalError, match="4xx") as exc_info:
                await adapter.embed(inputs)

        # Must NOT be a retryable error
        assert not isinstance(exc_info.value, RetryableError)
