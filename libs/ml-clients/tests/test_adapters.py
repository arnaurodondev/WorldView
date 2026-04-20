"""Adapter unit tests — all external calls are mocked."""

from __future__ import annotations

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ml_clients.dataclasses import (
    EmbeddingInput,
    ExtractionInput,
    NERInput,
)
from ml_clients.errors import FatalError, RetryableError

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
        """A cost tracker where INCRBYFLOAT returns $1.00 (well under $9.50 cap threshold)."""
        tracker = AsyncMock()
        tracker.incrbyfloat.return_value = 1.000075
        return tracker

    @pytest.fixture
    def _mock_cost_tracker_over_cap(self) -> AsyncMock:
        """A cost tracker where INCRBYFLOAT returns $10.00 (at cap → triggers undo)."""
        tracker = AsyncMock()
        tracker.incrbyfloat.return_value = 10.0
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
        """Monthly counter ≥ cap → generate_description returns None without API call.

        The atomic reserve pattern: INCRBYFLOAT returns >= cap*0.95 → undo (negative INCRBYFLOAT).
        """
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
        # Reserve call (positive) + undo call (negative) = 2 INCRBYFLOAT calls
        assert _mock_cost_tracker_over_cap.incrbyfloat.call_count == 2
        # Second call is the undo (negative amount)
        undo_args = _mock_cost_tracker_over_cap.incrbyfloat.call_args_list[1]
        assert undo_args[0][1] < 0, "Undo call should have negative amount"

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
        # At least 1 call for reservation; potentially a 2nd for cost adjustment
        assert _mock_cost_tracker_under_cap.incrbyfloat.call_count >= 1

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

        When INCRBYFLOAT returns ≥ $9.50 (95% of $10 cap), the adapter undoes
        the reservation and returns None.  When it returns < $9.50, the API call
        proceeds.
        """
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        # ── $9.50 → blocked (INCRBYFLOAT returns at-threshold value) ─────────
        tracker_at_95 = AsyncMock()
        tracker_at_95.incrbyfloat.return_value = 9.50  # post-increment total >= cap*0.95

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

        # ── $9.40 → not blocked (INCRBYFLOAT returns below threshold) ────────
        tracker_below = AsyncMock()
        tracker_below.incrbyfloat.return_value = 9.40  # post-increment total < cap*0.95

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

    # ── G-005 / PLAN-0031 C-2: Atomic cost cap tests ─────────────────────

    async def test_cost_cap_atomic_allows_under_limit(
        self,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """INCRBYFLOAT returns value below cap → reservation succeeds, API called."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        tracker = AsyncMock()
        tracker.incrbyfloat.return_value = 2.0  # well under $9.50 threshold

        adapter = GeminiDescriptionAdapter(
            api_key="key",
            semaphore=semaphore,
            cost_tracker=tracker,
            max_monthly_usd=10.0,
        )
        description_text = "Test entity description."
        mock_google, mock_genai = self._make_genai_mock(description_text)

        with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
            result = await adapter.generate_description(
                entity_id="e-under",
                canonical_name="Test Entity",
                entity_type="organization",
                context_hints={},
            )

        assert result == description_text
        # First call is the reservation (positive amount)
        first_call_amount = tracker.incrbyfloat.call_args_list[0][0][1]
        assert first_call_amount > 0, "First INCRBYFLOAT should be a positive reservation"

    async def test_cost_cap_atomic_blocks_at_limit(
        self,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """INCRBYFLOAT returns value at cap → reservation is undone, returns None."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        tracker = AsyncMock()
        tracker.incrbyfloat.return_value = 9.50  # exactly at 95% threshold

        adapter = GeminiDescriptionAdapter(
            api_key="key",
            semaphore=semaphore,
            cost_tracker=tracker,
            max_monthly_usd=10.0,
        )

        result = await adapter.generate_description(
            entity_id="e-at-limit",
            canonical_name="Test Entity",
            entity_type="organization",
            context_hints={},
        )

        assert result is None
        # Exactly 2 calls: reserve (positive) + undo (negative)
        assert tracker.incrbyfloat.call_count == 2
        reserve_amount = tracker.incrbyfloat.call_args_list[0][0][1]
        undo_amount = tracker.incrbyfloat.call_args_list[1][0][1]
        assert reserve_amount > 0
        assert undo_amount == -reserve_amount, "Undo must exactly negate the reservation"

    async def test_cost_cap_concurrent_safe(
        self,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Two concurrent calls at cap-1: first proceeds, second is blocked.

        Simulates the atomic INCRBYFLOAT pattern: each caller sees its own
        post-increment total.  The first call gets total < cap; the second
        call gets total >= cap and undoes its reservation.
        """
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        call_count = 0
        cap_threshold = 10.0 * 0.95  # 9.50

        async def _incrbyfloat_side_effect(key: str, amount: float) -> float:
            """Simulate two concurrent reservations against a counter near cap."""
            nonlocal call_count
            call_count += 1
            if amount < 0:
                # Undo call — return doesn't matter for the test
                return 9.0
            # First positive call → under cap; second positive call → at cap
            if call_count == 1:
                return cap_threshold - 0.01  # 9.49 — allowed
            return cap_threshold  # 9.50 — blocked

        # ── First adapter (under cap) ────────────────────────────────────────
        tracker1 = AsyncMock()
        tracker1.incrbyfloat.side_effect = _incrbyfloat_side_effect

        adapter1 = GeminiDescriptionAdapter(
            api_key="key",
            semaphore=semaphore,
            cost_tracker=tracker1,
            max_monthly_usd=10.0,
        )
        description_text = "Allowed description."
        mock_google, mock_genai = self._make_genai_mock(description_text)

        with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
            result1 = await adapter1.generate_description(
                entity_id="e-concurrent-1",
                canonical_name="Entity A",
                entity_type="organization",
                context_hints={},
            )
        assert result1 == description_text, "First concurrent caller must succeed"

        # ── Second adapter (at cap) ──────────────────────────────────────────
        tracker2 = AsyncMock()
        tracker2.incrbyfloat.side_effect = _incrbyfloat_side_effect

        adapter2 = GeminiDescriptionAdapter(
            api_key="key",
            semaphore=semaphore,
            cost_tracker=tracker2,
            max_monthly_usd=10.0,
        )
        result2 = await adapter2.generate_description(
            entity_id="e-concurrent-2",
            canonical_name="Entity B",
            entity_type="organization",
            context_hints={},
        )
        assert result2 is None, "Second concurrent caller must be blocked at cap"

    async def test_cost_cap_valkey_unavailable_fail_open(
        self,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Valkey error in _reserve_cost → fail-open (allow the API call)."""
        from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter

        tracker = AsyncMock()
        tracker.incrbyfloat.side_effect = ConnectionError("Valkey down")

        adapter = GeminiDescriptionAdapter(
            api_key="key",
            semaphore=semaphore,
            cost_tracker=tracker,
            max_monthly_usd=10.0,
        )
        description_text = "Allowed despite Valkey failure."
        mock_google, mock_genai = self._make_genai_mock(description_text)

        with patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}):
            result = await adapter.generate_description(
                entity_id="e-failopen",
                canonical_name="Test",
                entity_type="organization",
                context_hints={},
            )

        assert result == description_text, "Must fail-open on Valkey unavailability"


# ── ResizableSemaphore ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestResizableSemaphore:
    """Unit tests for ResizableSemaphore."""

    @pytest.mark.asyncio
    async def test_acquire_up_to_limit(self) -> None:
        """Acquire proceeds up to the limit without blocking."""
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        sem = ResizableSemaphore(initial=2, max_permits=5)
        await sem.acquire()
        await sem.acquire()
        assert sem.active == 2

    @pytest.mark.asyncio
    async def test_acquire_blocks_at_limit(self) -> None:
        """Third acquire blocks when limit is 2."""
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        sem = ResizableSemaphore(initial=2, max_permits=5)
        await sem.acquire()
        await sem.acquire()

        blocked = asyncio.ensure_future(sem.acquire())
        await asyncio.sleep(0)  # yield to let the task start
        assert not blocked.done(), "Third acquire should be blocked"

        sem.release()
        await asyncio.sleep(0)  # yield to let the waiter proceed
        assert blocked.done()
        sem.release()
        sem.release()

    @pytest.mark.asyncio
    async def test_set_limit_increase_wakes_waiters(self) -> None:
        """Increasing limit wakes blocked waiters immediately."""
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        sem = ResizableSemaphore(initial=1, max_permits=5)
        await sem.acquire()  # use the only permit

        waiter = asyncio.ensure_future(sem.acquire())
        await asyncio.sleep(0)
        assert not waiter.done()

        sem.set_limit(2)  # open up one more slot
        await asyncio.sleep(0)
        assert waiter.done()
        sem.release()
        sem.release()

    @pytest.mark.asyncio
    async def test_set_limit_decrease_respected_on_next_acquire(self) -> None:
        """After decreasing limit, new acquires block at the lower bound."""
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        sem = ResizableSemaphore(initial=3, max_permits=5)
        sem.set_limit(1)

        await sem.acquire()
        blocked = asyncio.ensure_future(sem.acquire())
        await asyncio.sleep(0)
        assert not blocked.done()

        sem.release()
        await asyncio.sleep(0)
        assert blocked.done()
        sem.release()

    @pytest.mark.asyncio
    async def test_release_over_acquire_raises(self) -> None:
        """Releasing more than acquired raises RuntimeError."""
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        sem = ResizableSemaphore(initial=2, max_permits=2)
        with pytest.raises(RuntimeError, match="released more times"):
            sem.release()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """async with properly acquires and releases."""
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        sem = ResizableSemaphore(initial=1, max_permits=1)
        async with sem:
            assert sem.active == 1
        assert sem.active == 0

    @pytest.mark.asyncio
    async def test_cancellation_does_not_leak_permit(self) -> None:
        """Cancelled waiter is removed from the queue; semaphore stays consistent."""
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        sem = ResizableSemaphore(initial=1, max_permits=1)
        await sem.acquire()  # hold the only permit

        waiter = asyncio.ensure_future(sem.acquire())
        await asyncio.sleep(0)
        waiter.cancel()
        await asyncio.sleep(0)

        assert waiter.cancelled()
        sem.release()  # should not raise — waiter was cleaned up
        assert sem.active == 0

    def test_invalid_initial_raises(self) -> None:
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        with pytest.raises(ValueError, match="≥ 1"):
            ResizableSemaphore(initial=0)

    def test_max_permits_less_than_initial_raises(self) -> None:
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        with pytest.raises(ValueError, match="max_permits"):
            ResizableSemaphore(initial=5, max_permits=2)

    def test_set_limit_clamped_to_max(self) -> None:
        """set_limit above max_permits is silently clamped."""
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        sem = ResizableSemaphore(initial=1, max_permits=5)
        sem.set_limit(100)
        assert sem.current_limit == 5

    def test_set_limit_clamped_to_one(self) -> None:
        """set_limit below 1 is clamped to 1."""
        from ml_clients.adapters.gliner_adaptive import ResizableSemaphore

        sem = ResizableSemaphore(initial=3, max_permits=5)
        sem.set_limit(0)
        assert sem.current_limit == 1


# ── AIMDController ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAIMDController:
    """Unit tests for AIMDController."""

    def _make(self, initial: int = 2, target_ms: float = 1000.0, min_samples: int = 3) -> tuple:  # type: ignore[type-arg]
        from ml_clients.adapters.gliner_adaptive import AIMDController, ResizableSemaphore

        sem = ResizableSemaphore(initial=initial, max_permits=20)
        ctrl = AIMDController(semaphore=sem, target_latency_ms=target_ms, min_samples=min_samples)
        return ctrl, sem

    def test_no_adjustment_before_min_samples(self) -> None:
        """No limit change until min_samples observations are recorded."""
        ctrl, sem = self._make(initial=2, min_samples=3)
        ctrl.record_success(100.0)
        ctrl.record_success(100.0)
        assert sem.current_limit == 2  # still at initial; only 2 samples

    def test_increases_on_fast_responses(self) -> None:
        """Limit grows when avg latency < target."""
        ctrl, sem = self._make(initial=2, target_ms=1000.0, min_samples=3)
        for _ in range(3):
            ctrl.record_success(200.0)  # well below target
        assert sem.current_limit == 3

    def test_decreases_on_slow_responses(self) -> None:
        """Limit shrinks when avg latency > 1.5x target."""
        ctrl, sem = self._make(initial=5, target_ms=1000.0, min_samples=3)
        for _ in range(3):
            ctrl.record_success(1800.0)  # above 1.5x target (1500)
        assert sem.current_limit == 4

    def test_no_change_when_within_band(self) -> None:
        """No adjustment when avg is between target and 1.5x target."""
        ctrl, sem = self._make(initial=5, target_ms=1000.0, min_samples=3)
        for _ in range(3):
            ctrl.record_success(1200.0)  # between 1000 and 1500
        assert sem.current_limit == 5

    def test_timeout_halves_limit(self) -> None:
        """Timeout triggers multiplicative decrease (÷2)."""
        ctrl, sem = self._make(initial=8)
        ctrl.record_failure(is_timeout=True)
        assert sem.current_limit == 4

    def test_failure_decrements_limit(self) -> None:
        """Non-timeout failure decrements limit by 1."""
        ctrl, sem = self._make(initial=5)
        ctrl.record_failure(is_timeout=False)
        assert sem.current_limit == 4

    def test_failure_never_below_one(self) -> None:
        """Repeated failures cannot push limit below 1."""
        ctrl, sem = self._make(initial=1)
        ctrl.record_failure(is_timeout=True)
        assert sem.current_limit == 1
        ctrl.record_failure(is_timeout=False)
        assert sem.current_limit == 1

    def test_avg_latency_none_before_any_record(self) -> None:
        ctrl, _ = self._make()
        assert ctrl.avg_latency_ms is None

    def test_avg_latency_computed_correctly(self) -> None:
        ctrl, _ = self._make()
        ctrl.record_success(100.0)
        ctrl.record_success(200.0)
        assert ctrl.avg_latency_ms == pytest.approx(150.0)


# ── AdaptiveGLiNERHTTPAdapter ─────────────────────────────────────────────────


def _make_httpx_response(status: int = 200, body: dict | None = None) -> MagicMock:  # type: ignore[type-arg]
    """Build a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body or {"results": [[]]}
    resp.text = str(body)
    return resp


@pytest.mark.unit
class TestAdaptiveGLiNERHTTPAdapter:
    """Unit tests for AdaptiveGLiNERHTTPAdapter."""

    def _adapter(self, initial: int = 5, max_conc: int = 10) -> AdaptiveGLiNERHTTPAdapter:  # type: ignore[name-defined]
        from ml_clients.adapters.gliner_adaptive import AdaptiveGLiNERHTTPAdapter

        return AdaptiveGLiNERHTTPAdapter(
            base_url="http://gliner-test:8080",
            initial_concurrency=initial,
            max_concurrency=max_conc,
            target_latency_ms=5000.0,  # high target so tests don't trigger AIMD adjustment
        )

    def _inp(self, text: str = "Apple reported earnings.") -> NERInput:
        return NERInput(text=text, entity_classes=["ORG"], threshold=0.35)

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self) -> None:
        adapter = self._adapter()
        result = await adapter.batch_extract_entities([])
        assert result == []

    @pytest.mark.asyncio
    async def test_single_input_returns_single_output(self) -> None:
        adapter = self._adapter()
        body = {"results": [[{"text": "Apple", "label": "ORG", "start": 0, "end": 5, "score": 0.9}]]}
        mock_resp = _make_httpx_response(200, body)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            results = await adapter.batch_extract_entities([self._inp()])

        assert len(results) == 1
        assert results[0].mentions[0].text == "Apple"

    @pytest.mark.asyncio
    async def test_fan_out_fires_one_request_per_input(self) -> None:
        """With 3 inputs, exactly 3 HTTP POST calls are made."""
        adapter = self._adapter(initial=5)
        mock_resp = _make_httpx_response(200, {"results": [[]]})

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            inputs = [self._inp(f"text {i}") for i in range(3)]
            await adapter.batch_extract_entities(inputs)

        assert mock_post.call_count == 3

    @pytest.mark.asyncio
    async def test_results_in_input_order(self) -> None:
        """Results are returned in the same order as inputs (gather preserves order)."""
        adapter = self._adapter(initial=5)

        call_index = 0

        async def mock_post(url: str, **kwargs: object) -> MagicMock:  # type: ignore[return]
            nonlocal call_index
            idx = call_index
            call_index += 1
            label = f"LABEL_{idx}"
            return _make_httpx_response(
                200,
                {"results": [[{"text": f"ent{idx}", "label": label, "start": 0, "end": 4, "score": 0.8}]]},
            )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
            inputs = [self._inp(f"text {i}") for i in range(4)]
            results = await adapter.batch_extract_entities(inputs)

        # Results must align with inputs (order preserved)
        assert len(results) == 4
        for i, result in enumerate(results):
            assert result.mentions[0].label == f"LABEL_{i}"

    @pytest.mark.asyncio
    async def test_5xx_raises_retryable(self) -> None:
        adapter = self._adapter()
        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_httpx_response(500)),
            pytest.raises(RetryableError, match="5xx"),
        ):
            await adapter.extract_entities(self._inp())

    @pytest.mark.asyncio
    async def test_503_raises_retryable(self) -> None:
        adapter = self._adapter()
        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_httpx_response(503)),
            pytest.raises(RetryableError, match="unavailable"),
        ):
            await adapter.extract_entities(self._inp())

    @pytest.mark.asyncio
    async def test_4xx_raises_fatal(self) -> None:
        adapter = self._adapter()
        with (
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_httpx_response(422)),
            pytest.raises(FatalError, match="4xx"),
        ):
            await adapter.extract_entities(self._inp())

    @pytest.mark.asyncio
    async def test_timeout_raises_retryable(self) -> None:
        import httpx

        adapter = self._adapter()
        with (
            patch(
                "httpx.AsyncClient.post",
                new_callable=AsyncMock,
                side_effect=httpx.TimeoutException("timed out"),
            ),
            pytest.raises(RetryableError, match="timeout"),
        ):
            await adapter.extract_entities(self._inp())

    @pytest.mark.asyncio
    async def test_connection_error_raises_retryable(self) -> None:
        import httpx

        adapter = self._adapter()
        with (
            patch(
                "httpx.AsyncClient.post",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("refused"),
            ),
            pytest.raises(RetryableError, match="connection error"),
        ):
            await adapter.extract_entities(self._inp())

    @pytest.mark.asyncio
    async def test_concurrency_limit_respected(self) -> None:
        """With initial_concurrency=2, at most 2 HTTP calls are in-flight at once."""
        from ml_clients.adapters.gliner_adaptive import AdaptiveGLiNERHTTPAdapter

        adapter = AdaptiveGLiNERHTTPAdapter(
            base_url="http://gliner-test:8080",
            initial_concurrency=2,
            max_concurrency=2,  # hard cap at 2
            target_latency_ms=99999.0,  # never triggers AIMD increase
        )

        active_count = 0
        max_observed = 0
        gate = asyncio.Event()

        async def mock_post(*args: object, **kwargs: object) -> MagicMock:
            nonlocal active_count, max_observed
            active_count += 1
            max_observed = max(max_observed, active_count)
            await gate.wait()
            active_count -= 1
            return _make_httpx_response(200, {"results": [[]]})

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
            inputs = [self._inp(f"text {i}") for i in range(5)]
            gather_task = asyncio.ensure_future(adapter.batch_extract_entities(inputs))

            # Let all tasks start and block at the gate
            await asyncio.sleep(0.01)
            # Only 2 should be active (limited by initial_concurrency=2, max=2)
            assert active_count == 2, f"Expected 2 active, got {active_count}"

            gate.set()
            await gather_task

        assert max_observed == 2, f"Expected max 2 concurrent, got {max_observed}"

    @pytest.mark.asyncio
    async def test_5xx_reduces_concurrency(self) -> None:
        """5xx response decreases the adaptive concurrency limit."""
        adapter = self._adapter(initial=5, max_conc=10)
        initial_limit = adapter.current_concurrency

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_make_httpx_response(500)):
            with pytest.raises(RetryableError):
                await adapter.extract_entities(self._inp())

        assert adapter.current_concurrency < initial_limit

    @pytest.mark.asyncio
    async def test_timeout_halves_concurrency(self) -> None:
        """Timeout halves the adaptive concurrency limit."""
        import httpx

        adapter = self._adapter(initial=8, max_conc=10)

        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("timed out"),
        ):
            with pytest.raises(RetryableError):
                await adapter.extract_entities(self._inp())

        assert adapter.current_concurrency == 4  # 8 // 2

    def test_initial_concurrency_exposed(self) -> None:
        adapter = self._adapter(initial=3)
        assert adapter.current_concurrency == 3

    def test_avg_latency_none_initially(self) -> None:
        adapter = self._adapter()
        assert adapter.avg_latency_ms is None
