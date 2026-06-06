"""Unit tests for the primary → fallback adapter wrappers (LIB-004 / TASK-W4-02).

Every test uses ``AsyncMock``-backed stubs that conform structurally to
the relevant Protocol. We don't need the real DeepInfra/Ollama adapters —
the wrapper's contract is "delegate to .embed/.extract_entities/.extract,
catch RetryableError, retry on the fallback".

Scenarios per wrapper:
  1. Primary succeeds → primary result returned, fallback NOT called.
  2. Primary raises RetryableError → fallback invoked, fallback result
     returned.
  3. Primary raises FatalError → propagates immediately; fallback NOT
     called (the request is malformed; fallback would fail identically).
  4. Both fail (Retryable → Retryable) → exception from fallback
     propagates to caller.

The third scenario also covers RateLimitError because it is a subclass
of RetryableError — exercised once for embeddings as the integration
proof, no need to repeat across every wrapper.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from ml_clients.dataclasses import (
    EmbeddingInput,
    EmbeddingOutput,
    EntityMention,
    ExtractionInput,
    ExtractionOutput,
    NERInput,
    NEROutput,
)
from ml_clients.errors import FatalError, RateLimitError, RetryableError
from ml_clients.fallback import (
    FallbackEmbeddingClient,
    FallbackExtractionClient,
    FallbackNERClient,
)

# ── Factories ─────────────────────────────────────────────────────────────────


def _emb_inputs() -> list[EmbeddingInput]:
    return [EmbeddingInput(text="Apple Inc.", model_id="bge-large-en-v1.5")]


def _emb_output(*, marker: str) -> list[EmbeddingOutput]:
    # ``marker`` lets tests assert WHICH adapter produced the result by
    # encoding the source in model_id without needing identity comparison.
    return [EmbeddingOutput(embedding=[0.1] * 1024, model_id=marker, dimension=1024)]


def _ner_input() -> NERInput:
    return NERInput(text="Apple announced earnings.", entity_classes=["ORG"])


def _ner_output(*, marker: str) -> NEROutput:
    return NEROutput(
        mentions=[EntityMention(text=marker, label="ORG", start=0, end=5, score=0.9)],
    )


def _extraction_input() -> ExtractionInput:
    return ExtractionInput(
        prompt="Extract JSON",
        context="Apple Inc.",
        output_schema={"type": "object"},
        model_id="meta-llama/Meta-Llama-3.1-8B-Instruct",
    )


def _extraction_output(*, marker: str) -> ExtractionOutput:
    return ExtractionOutput(result={"source": marker}, raw_response=marker, model_id=marker)


# ── FallbackEmbeddingClient ───────────────────────────────────────────────────


class TestFallbackEmbeddingClient:
    async def test_primary_success_short_circuits(self) -> None:
        """Happy path — primary returns; fallback is never invoked."""
        primary = AsyncMock()
        primary.embed = AsyncMock(return_value=_emb_output(marker="primary"))
        fallback = AsyncMock()
        fallback.embed = AsyncMock(return_value=_emb_output(marker="fallback"))

        client = FallbackEmbeddingClient(primary=primary, fallback=fallback)
        result = await client.embed(_emb_inputs())

        assert result[0].model_id == "primary"
        primary.embed.assert_awaited_once()
        fallback.embed.assert_not_awaited()

    async def test_retryable_triggers_fallback(self) -> None:
        """RetryableError on primary → fallback is invoked and its result returned."""
        primary = AsyncMock()
        primary.embed = AsyncMock(side_effect=RetryableError("DeepInfra 5xx"))
        fallback = AsyncMock()
        fallback.embed = AsyncMock(return_value=_emb_output(marker="fallback"))

        client = FallbackEmbeddingClient(primary=primary, fallback=fallback)
        result = await client.embed(_emb_inputs())

        assert result[0].model_id == "fallback"
        primary.embed.assert_awaited_once()
        fallback.embed.assert_awaited_once()

    async def test_rate_limit_triggers_fallback(self) -> None:
        """RateLimitError is a RetryableError subclass → must trigger fallback."""
        primary = AsyncMock()
        primary.embed = AsyncMock(
            side_effect=RateLimitError("DeepInfra 429", retry_after=30),
        )
        fallback = AsyncMock()
        fallback.embed = AsyncMock(return_value=_emb_output(marker="fallback"))

        client = FallbackEmbeddingClient(primary=primary, fallback=fallback)
        result = await client.embed(_emb_inputs())

        assert result[0].model_id == "fallback"
        fallback.embed.assert_awaited_once()

    async def test_fatal_propagates_without_fallback(self) -> None:
        """FatalError (4xx/auth) propagates; fallback NOT invoked.

        Rationale: the same malformed request would fail identically on
        the secondary backend, so doubling latency adds no value.
        """
        primary = AsyncMock()
        primary.embed = AsyncMock(side_effect=FatalError("DeepInfra 401 Unauthorized"))
        fallback = AsyncMock()
        fallback.embed = AsyncMock(return_value=_emb_output(marker="fallback"))

        client = FallbackEmbeddingClient(primary=primary, fallback=fallback)

        with pytest.raises(FatalError, match="401"):
            await client.embed(_emb_inputs())

        primary.embed.assert_awaited_once()
        fallback.embed.assert_not_awaited()

    async def test_both_retryable_propagates(self) -> None:
        """Primary + fallback both fail with RetryableError → fallback's exception bubbles up."""
        primary = AsyncMock()
        primary.embed = AsyncMock(side_effect=RetryableError("primary timeout"))
        fallback = AsyncMock()
        fallback.embed = AsyncMock(side_effect=RetryableError("Ollama 5xx"))

        client = FallbackEmbeddingClient(primary=primary, fallback=fallback)

        with pytest.raises(RetryableError, match="Ollama 5xx"):
            await client.embed(_emb_inputs())

        primary.embed.assert_awaited_once()
        fallback.embed.assert_awaited_once()


# ── FallbackNERClient ─────────────────────────────────────────────────────────


class TestFallbackNERClient:
    async def test_extract_entities_primary_success(self) -> None:
        primary = AsyncMock()
        primary.extract_entities = AsyncMock(return_value=_ner_output(marker="primary"))
        fallback = AsyncMock()
        fallback.extract_entities = AsyncMock(return_value=_ner_output(marker="fallback"))

        client = FallbackNERClient(primary=primary, fallback=fallback)
        result = await client.extract_entities(_ner_input())

        assert result.mentions[0].text == "primary"
        fallback.extract_entities.assert_not_awaited()

    async def test_extract_entities_retryable_triggers_fallback(self) -> None:
        primary = AsyncMock()
        primary.extract_entities = AsyncMock(side_effect=RetryableError("GLiNER 5xx"))
        fallback = AsyncMock()
        fallback.extract_entities = AsyncMock(return_value=_ner_output(marker="fallback"))

        client = FallbackNERClient(primary=primary, fallback=fallback)
        result = await client.extract_entities(_ner_input())

        assert result.mentions[0].text == "fallback"

    async def test_extract_entities_fatal_propagates(self) -> None:
        primary = AsyncMock()
        primary.extract_entities = AsyncMock(side_effect=FatalError("400 bad request"))
        fallback = AsyncMock()
        fallback.extract_entities = AsyncMock(return_value=_ner_output(marker="fallback"))

        client = FallbackNERClient(primary=primary, fallback=fallback)

        with pytest.raises(FatalError):
            await client.extract_entities(_ner_input())
        fallback.extract_entities.assert_not_awaited()

    async def test_batch_extract_entities_retryable_triggers_fallback(self) -> None:
        """Batch path is wired identically to the single-input path."""
        primary = AsyncMock()
        primary.batch_extract_entities = AsyncMock(side_effect=RetryableError("GLiNER timeout"))
        fallback = AsyncMock()
        fallback.batch_extract_entities = AsyncMock(
            return_value=[_ner_output(marker="fallback")],
        )

        client = FallbackNERClient(primary=primary, fallback=fallback)
        result = await client.batch_extract_entities([_ner_input()])

        assert result[0].mentions[0].text == "fallback"


# ── FallbackExtractionClient ──────────────────────────────────────────────────


class TestFallbackExtractionClient:
    async def test_primary_success(self) -> None:
        primary = AsyncMock()
        primary.extract = AsyncMock(return_value=_extraction_output(marker="primary"))
        fallback = AsyncMock()
        fallback.extract = AsyncMock(return_value=_extraction_output(marker="fallback"))

        client = FallbackExtractionClient(primary=primary, fallback=fallback)
        result = await client.extract(_extraction_input())

        assert result.result == {"source": "primary"}
        fallback.extract.assert_not_awaited()

    async def test_retryable_triggers_fallback(self) -> None:
        primary = AsyncMock()
        primary.extract = AsyncMock(side_effect=RetryableError("DeepInfra 503"))
        fallback = AsyncMock()
        fallback.extract = AsyncMock(return_value=_extraction_output(marker="fallback"))

        client = FallbackExtractionClient(primary=primary, fallback=fallback)
        result = await client.extract(_extraction_input())

        assert result.result == {"source": "fallback"}

    async def test_fatal_propagates(self) -> None:
        primary = AsyncMock()
        primary.extract = AsyncMock(side_effect=FatalError("401"))
        fallback = AsyncMock()
        fallback.extract = AsyncMock(return_value=_extraction_output(marker="fallback"))

        client = FallbackExtractionClient(primary=primary, fallback=fallback)

        with pytest.raises(FatalError):
            await client.extract(_extraction_input())
        fallback.extract.assert_not_awaited()

    async def test_both_fail_propagates_fallback_error(self) -> None:
        primary = AsyncMock()
        primary.extract = AsyncMock(side_effect=RetryableError("primary 5xx"))
        fallback = AsyncMock()
        fallback.extract = AsyncMock(side_effect=RetryableError("Ollama down"))

        client = FallbackExtractionClient(primary=primary, fallback=fallback)

        with pytest.raises(RetryableError, match="Ollama down"):
            await client.extract(_extraction_input())
