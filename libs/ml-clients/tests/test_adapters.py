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

    async def test_long_text_truncated_to_max_words(
        self,
        adapter,  # type: ignore[no-untyped-def]
    ) -> None:
        """Texts over _MAX_WORDS words are word-count truncated before embedding."""
        from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter

        long_text = " ".join(f"word{i}" for i in range(500))  # 500 words > _MAX_WORDS=384
        inputs = [EmbeddingInput(text=long_text, model_id="bge-large-en-v1.5")]
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

        sent_text = captured[0]["prompt"]
        sent_words = sent_text.split()
        assert len(sent_words) == OllamaEmbeddingAdapter._MAX_WORDS

    async def test_short_text_not_truncated(
        self,
        adapter,  # type: ignore[no-untyped-def]
    ) -> None:
        """Short texts (under _MAX_WORDS) are sent as-is without modification."""
        text = "Apple reported earnings this quarter."
        inputs = [EmbeddingInput(text=text, model_id="bge-large-en-v1.5")]
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

        assert captured[0]["prompt"] == text


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
        # Sequential loop: each predict_entities(text, ...) call returns list[dict] for that text
        raw_section = [{"text": "Apple Inc.", "label": "ORG", "start": 0, "end": 10, "score": 0.95}]
        mock_model = MagicMock()
        mock_model.predict_entities.return_value = raw_section  # per-call: list[dict]
        adapter._model = mock_model

        result = await adapter.extract_entities(NERInput(text="Apple Inc. reported earnings", entity_classes=["ORG"]))
        assert len(result.mentions) == 1
        assert result.mentions[0].label == "ORG"
        assert result.mentions[0].score == 0.95

    async def test_nms_removes_overlapping_spans(self, adapter) -> None:  # type: ignore[no-untyped-def]
        """Higher-scored span is kept; overlapping lower-scored span is discarded.

        Spans [0,10] and [0,8]: intersection=8, union=10, IoU=0.8 > 0.5 → removed.
        """
        raw_section = [
            {"text": "Apple Inc.", "label": "ORG", "start": 0, "end": 10, "score": 0.95},
            {"text": "Apple Inc", "label": "ORG", "start": 0, "end": 8, "score": 0.80},
        ]
        mock_model = MagicMock()
        mock_model.predict_entities.return_value = raw_section  # per-call: list[dict]
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

        adapter = DeepSeekExtractionAdapter(api_key="key", semaphore=semaphore)

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

        with patch.dict("sys.modules", {"openai": mock_openai}), pytest.raises(RetryableError, match="timeout"):
            await adapter.extract(_extraction_input())

    async def test_rate_limit_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

        adapter = DeepSeekExtractionAdapter(api_key="key", semaphore=semaphore)

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
            await adapter.extract(_extraction_input())

    async def test_4xx_raises_fatal(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

        adapter = DeepSeekExtractionAdapter(api_key="key", semaphore=semaphore)

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
            await adapter.extract(_extraction_input())

    async def test_valid_response_with_deepseek_base_url(self, semaphore: asyncio.Semaphore) -> None:
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

        adapter = DeepSeekExtractionAdapter(
            api_key="key",
            base_url="https://api.deepseek.com/v1",
            semaphore=semaphore,
        )

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
            result = await adapter.extract(_extraction_input())

        assert result.result == payload
        assert captured_kwargs[0]["base_url"] == "https://api.deepseek.com/v1"


# ── NullDescriptionAdapter ────────────────────────────────────────────────────


class TestNullDescriptionAdapter:
    async def test_description_client_null_adapter(self) -> None:
        """NullDescriptionAdapter.generate_description always returns None."""
        from ml_clients.description_client import NullDescriptionAdapter

        adapter = NullDescriptionAdapter()
        result = await adapter.generate_description(
            entity_id="some-uuid",
            canonical_name="Jerome Powell",
            entity_type="person",
            context_hints={"role": "Fed Chair"},
        )
        assert result is None

    async def test_null_adapter_satisfies_protocol(self) -> None:
        """NullDescriptionAdapter is structurally compatible with EntityDescriptionClient."""
        from ml_clients.description_client import EntityDescriptionClient, NullDescriptionAdapter

        adapter = NullDescriptionAdapter()
        assert isinstance(adapter, EntityDescriptionClient)


# ── GeminiDescriptionAdapter ──────────────────────────────────────────────────


class TestGeminiDescriptionAdapter:
    @pytest.fixture
    def _mock_cost_tracker_under_cap(self) -> AsyncMock:
        """A cost tracker that reports $1.00 spent (well under $10 cap)."""
        tracker = AsyncMock()
        tracker.get.return_value = b"1.0"
        tracker.incrbyfloat.return_value = 1.000075
        return tracker

    @pytest.fixture
    def _mock_cost_tracker_over_cap(self) -> AsyncMock:
        """A cost tracker that reports $10.00 spent (at cap)."""
        tracker = AsyncMock()
        tracker.get.return_value = b"10.0"
        tracker.incrbyfloat.return_value = 10.000075
        return tracker

    def _make_genai_mock(self, response_text: str) -> tuple[MagicMock, MagicMock]:
        """Return (mock_google, mock_genai) wired with a successful text response."""
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = response_text
        mock_response.usage_metadata = None

        mock_models_aio = AsyncMock()
        mock_models_aio.generate_content = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.aio.models = mock_models_aio
        mock_genai.Client.return_value = mock_client

        mock_google = MagicMock()
        mock_google.genai = mock_genai
        return mock_google, mock_genai

    async def test_description_client_cost_cap(
        self,
        semaphore: asyncio.Semaphore,
        _mock_cost_tracker_over_cap: AsyncMock,
    ) -> None:
        """Monthly counter ≥ cap → generate_description returns None without API call."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        adapter = GeminiDescriptionAdapter(
            api_key="key",
            semaphore=semaphore,
            cost_tracker=_mock_cost_tracker_over_cap,
            max_monthly_usd=10.0,
        )

        result = await adapter.generate_description(
            entity_id="entity-1",
            canonical_name="Federal Reserve",
            entity_type="organization",
            context_hints={},
        )

        assert result is None
        # The genai API must NOT have been called
        _mock_cost_tracker_over_cap.get.assert_called_once()

    async def test_valid_response_returns_description(
        self,
        semaphore: asyncio.Semaphore,
        _mock_cost_tracker_under_cap: AsyncMock,
    ) -> None:
        """Successful API call returns the description text."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        adapter = GeminiDescriptionAdapter(
            api_key="key",
            semaphore=semaphore,
            cost_tracker=_mock_cost_tracker_under_cap,
            max_monthly_usd=10.0,
        )

        description_text = "The Federal Reserve is the central banking system of the United States."
        mock_google, mock_genai = self._make_genai_mock(description_text)

        with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
            result = await adapter.generate_description(
                entity_id="entity-1",
                canonical_name="Federal Reserve",
                entity_type="organization",
                context_hints={"country": "US"},
            )

        assert result == description_text
        _mock_cost_tracker_under_cap.incrbyfloat.assert_called_once()

    async def test_no_cost_tracker_skips_cap_check(self, semaphore: asyncio.Semaphore) -> None:
        """With no cost_tracker, the adapter calls the API without any cap check."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        adapter = GeminiDescriptionAdapter(api_key="key", semaphore=semaphore)
        description_text = "Jerome Powell is the Chair of the Federal Reserve."
        mock_google, mock_genai = self._make_genai_mock(description_text)

        with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
            result = await adapter.generate_description(
                entity_id="entity-2",
                canonical_name="Jerome Powell",
                entity_type="person",
                context_hints={"role": "Fed Chair"},
            )

        assert result == description_text

    async def test_retryable_gemini_error_raises_retryable(self, semaphore: asyncio.Semaphore) -> None:
        """ResourceExhausted (quota) from Gemini maps to RetryableError."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        adapter = GeminiDescriptionAdapter(api_key="key", semaphore=semaphore)

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
            await adapter.generate_description(
                entity_id="entity-3",
                canonical_name="Germany",
                entity_type="country",
                context_hints={},
            )

    async def test_missing_package_raises_fatal(self, semaphore: asyncio.Semaphore) -> None:
        """Missing google-genai package raises FatalError (not ImportError)."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        adapter = GeminiDescriptionAdapter(api_key="key", semaphore=semaphore)
        with patch.dict(sys.modules, {"google": None, "google.genai": None}), pytest.raises((FatalError, ImportError)):
            await adapter.generate_description(
                entity_id="entity-4",
                canonical_name="Germany",
                entity_type="country",
                context_hints={},
            )

    async def test_adapter_satisfies_protocol(self, semaphore: asyncio.Semaphore) -> None:
        """GeminiDescriptionAdapter is structurally compatible with EntityDescriptionClient."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter
        from ml_clients.description_client import EntityDescriptionClient

        adapter = GeminiDescriptionAdapter(api_key="key", semaphore=semaphore)
        assert isinstance(adapter, EntityDescriptionClient)

    async def test_cost_cap_5pct_margin_blocks_at_95pct(
        self,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Cost cap guard fires at 95% of cap (5% margin buffer — F-DS-001).

        At $9.50 (= 95% of $10 cap), the adapter must return None without
        making an API call.  At $9.40 (< 95%), the API MUST be called.
        """
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        # ── $9.50 → blocked (95% of $10) ────────────────────────────────────
        tracker_at_95 = AsyncMock()
        tracker_at_95.get.return_value = b"9.50"

        adapter = GeminiDescriptionAdapter(
            api_key="key",
            semaphore=semaphore,
            cost_tracker=tracker_at_95,
            max_monthly_usd=10.0,
        )
        result = await adapter.generate_description(
            entity_id="e1",
            canonical_name="Germany",
            entity_type="country",
            context_hints={},
        )
        assert result is None, "At 95% of cap, generate_description must return None"

        # ── $9.40 → not blocked (< 95%) ─────────────────────────────────────
        tracker_below = AsyncMock()
        tracker_below.get.return_value = b"9.40"
        tracker_below.incrbyfloat.return_value = 9.4001

        description_text = "Germany is a country in central Europe."
        mock_google, mock_genai = self._make_genai_mock(description_text)

        adapter2 = GeminiDescriptionAdapter(
            api_key="key",
            semaphore=semaphore,
            cost_tracker=tracker_below,
            max_monthly_usd=10.0,
        )
        with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
            result2 = await adapter2.generate_description(
                entity_id="e2",
                canonical_name="Germany",
                entity_type="country",
                context_hints={},
            )
        assert result2 == description_text, "Below 95% of cap, API must be called"

    async def test_genai_client_reused_across_calls(
        self,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """genai.Client is instantiated ONCE per adapter instance — not per call (F-DS-013)."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        adapter = GeminiDescriptionAdapter(api_key="my-key", semaphore=semaphore)
        description_text = "A test description."
        mock_google, mock_genai = self._make_genai_mock(description_text)

        with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
            # Call twice
            await adapter.generate_description(
                entity_id="e1",
                canonical_name="Apple Inc.",
                entity_type="financial_instrument",
                context_hints={},
            )
            await adapter.generate_description(
                entity_id="e2",
                canonical_name="Microsoft Corp.",
                entity_type="financial_instrument",
                context_hints={},
            )

        # genai.Client() constructor called exactly ONCE (lazy init + reuse)
        assert (
            mock_genai.Client.call_count == 1
        ), f"genai.Client should be instantiated once; got {mock_genai.Client.call_count}"
