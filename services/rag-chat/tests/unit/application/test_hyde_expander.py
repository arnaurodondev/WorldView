"""Unit tests for HydeExpander (T-E-2-02).

Uses fakeredis for Valkey and lightweight async mocks for the LLM/embedding ports.

PLAN-0067 W11-3: RetrievalPlanBuilder tests removed — class deleted from chat path.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import fakeredis.aioredis
import pytest
from rag_chat.application.pipeline.hyde_expander import HydeExpander
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit


# ── Helpers ────────────────────────────────────────────────────────────────────


class _StreamingLlm:
    """Mock LLM that yields a fixed list of chunks."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
    ) -> AsyncGenerator[str, None]:
        for chunk in self._chunks:
            yield chunk


class _EmbeddingClient:
    """Mock embedding client returning a fixed-length vector."""

    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    async def embed(self, text: str) -> list[float]:
        return self._vector


@pytest.fixture()
def fake_valkey() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


_SAMPLE_EMBEDDING = [0.1, 0.2, 0.3]
_SAMPLE_CHUNKS = ["Apple ", "reported ", "strong ", "earnings."]
_EXPECTED_HYPOTHESIS = "Apple reported strong earnings."


# ── HydeExpander tests ─────────────────────────────────────────────────────────


class TestHydeExpander:
    async def test_hyde_skipped_for_financial_data(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """FINANCIAL_DATA intent → (None, None) — HyDE not activated."""
        llm = _StreamingLlm(_SAMPLE_CHUNKS)
        embedder = _EmbeddingClient(_SAMPLE_EMBEDDING)
        expander = HydeExpander(llm, embedder, fake_valkey)

        hypothesis, embedding = await expander.expand("What is Apple's current P/E ratio?", QueryIntent.FINANCIAL_DATA)

        assert hypothesis is None
        assert embedding is None

    async def test_hyde_generates_hypothesis(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """REASONING intent → non-empty hypothesis text and embedding vector."""
        llm = _StreamingLlm(_SAMPLE_CHUNKS)
        embedder = _EmbeddingClient(_SAMPLE_EMBEDDING)
        expander = HydeExpander(llm, embedder, fake_valkey)

        hypothesis, embedding = await expander.expand("Why is Apple's margin declining?", QueryIntent.REASONING)

        assert hypothesis == _EXPECTED_HYPOTHESIS
        assert embedding == _SAMPLE_EMBEDDING

    async def test_hyde_cached(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """Second call for the same query hits Valkey — LLM is not called again."""
        call_count = 0

        class _CountingLlm:
            async def stream(
                self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.1
            ) -> AsyncGenerator[str, None]:
                nonlocal call_count
                call_count += 1
                for chunk in _SAMPLE_CHUNKS:
                    yield chunk

        embedder = _EmbeddingClient(_SAMPLE_EMBEDDING)
        expander = HydeExpander(_CountingLlm(), embedder, fake_valkey)
        query = "Why did Apple's revenue grow?"

        await expander.expand(query, QueryIntent.REASONING)
        await expander.expand(query, QueryIntent.REASONING)

        assert call_count == 1  # LLM called only on the first request
