"""Unit tests for CompletionCache (T-E-1-02).

Uses fakeredis for an in-process Valkey simulation.
"""

from __future__ import annotations

from uuid import UUID

import fakeredis.aioredis
import pytest
from rag_chat.application.caching.completion_cache import CompletionCache

pytestmark = pytest.mark.unit

_THREAD_ID = UUID("00000000-0000-0000-0000-000000000001")

_SAMPLE_RESPONSE: dict = {  # type: ignore[type-arg]
    "answer": "Apple's P/E ratio is approximately 28x.",
    "citations": [{"source_id": "abc", "title": "Reuters"}],
}


@pytest.fixture()
def fake_valkey() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


class TestCompletionCache:
    async def test_completion_cache_miss(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """Cache miss — unknown key returns None."""
        cache = CompletionCache(fake_valkey)
        result = await cache.get("What is Apple's P/E?", _THREAD_ID)
        assert result is None

    async def test_completion_cache_hit(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """Get after set returns the cached dict."""
        cache = CompletionCache(fake_valkey)
        message = "What is Apple's P/E ratio?"
        await cache.set(message, _THREAD_ID, _SAMPLE_RESPONSE)
        result = await cache.get(message, _THREAD_ID)
        assert result == _SAMPLE_RESPONSE

    async def test_completion_cache_miss_no_thread(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """Cache miss with thread_id=None returns None."""
        cache = CompletionCache(fake_valkey)
        result = await cache.get("What is TSLA's revenue?", None)
        assert result is None

    async def test_completion_cache_hit_no_thread(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """Cache hit with thread_id=None works correctly."""
        cache = CompletionCache(fake_valkey)
        message = "What is TSLA's revenue?"
        await cache.set(message, None, _SAMPLE_RESPONSE)
        result = await cache.get(message, None)
        assert result == _SAMPLE_RESPONSE

    async def test_completion_cache_different_threads_are_isolated(
        self, fake_valkey: fakeredis.aioredis.FakeRedis
    ) -> None:
        """Same message under different thread IDs maps to different cache entries."""
        cache = CompletionCache(fake_valkey)
        message = "What is Apple's P/E?"
        thread_a = UUID("00000000-0000-0000-0000-000000000001")
        thread_b = UUID("00000000-0000-0000-0000-000000000002")
        response_a = {"answer": "Response A"}
        response_b = {"answer": "Response B"}

        await cache.set(message, thread_a, response_a)
        await cache.set(message, thread_b, response_b)

        assert await cache.get(message, thread_a) == response_a
        assert await cache.get(message, thread_b) == response_b

    async def test_completion_cache_key_format(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """Cache keys follow the expected rag:v1:completion: prefix."""
        cache = CompletionCache(fake_valkey)
        await cache.set("test message", _THREAD_ID, {"answer": "ok"})
        keys = await fake_valkey.keys("rag:v1:completion:*")
        assert len(keys) == 1
        assert keys[0].startswith(b"rag:v1:completion:")
