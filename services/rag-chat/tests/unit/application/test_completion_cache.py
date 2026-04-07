"""Unit tests for CompletionCache (T-E-1-02).

Uses a mock ValkeyClient to verify get/set behaviour without a live connection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from rag_chat.application.caching.completion_cache import CompletionCache

pytestmark = pytest.mark.unit

_THREAD_ID = UUID("00000000-0000-0000-0000-000000000001")

_SAMPLE_RESPONSE: dict = {  # type: ignore[type-arg]
    "answer": "Apple's P/E ratio is approximately 28x.",
    "citations": [{"source_id": "abc", "title": "Reuters"}],
}


def _make_valkey() -> MagicMock:
    """Return a MagicMock that behaves like a ValkeyClient with in-memory storage."""
    store: dict[str, str] = {}
    valkey = MagicMock()

    async def _get(key: str) -> str | None:
        return store.get(key)

    async def _set(key: str, value: str, *, ttl: int | None = None) -> None:
        store[key] = value

    valkey.get = AsyncMock(side_effect=_get)
    valkey.set = AsyncMock(side_effect=_set)
    valkey._store = store  # expose for inspection
    return valkey


class TestCompletionCache:
    async def test_completion_cache_miss(self) -> None:
        """Cache miss — unknown key returns None."""
        cache = CompletionCache(_make_valkey())
        result = await cache.get("What is Apple's P/E?", _THREAD_ID)
        assert result is None

    async def test_completion_cache_hit(self) -> None:
        """Get after set returns the cached dict."""
        valkey = _make_valkey()
        cache = CompletionCache(valkey)
        message = "What is Apple's P/E ratio?"
        await cache.set(message, _THREAD_ID, _SAMPLE_RESPONSE)
        result = await cache.get(message, _THREAD_ID)
        assert result == _SAMPLE_RESPONSE

    async def test_completion_cache_miss_no_thread(self) -> None:
        """Cache miss with thread_id=None returns None."""
        cache = CompletionCache(_make_valkey())
        result = await cache.get("What is TSLA's revenue?", None)
        assert result is None

    async def test_completion_cache_hit_no_thread(self) -> None:
        """Cache hit with thread_id=None works correctly."""
        valkey = _make_valkey()
        cache = CompletionCache(valkey)
        message = "What is TSLA's revenue?"
        await cache.set(message, None, _SAMPLE_RESPONSE)
        result = await cache.get(message, None)
        assert result == _SAMPLE_RESPONSE

    async def test_completion_cache_different_threads_are_isolated(self) -> None:
        """Same message under different thread IDs maps to different cache entries."""
        valkey = _make_valkey()
        cache = CompletionCache(valkey)
        message = "What is Apple's P/E?"
        thread_a = UUID("00000000-0000-0000-0000-000000000001")
        thread_b = UUID("00000000-0000-0000-0000-000000000002")
        response_a = {"answer": "Response A"}
        response_b = {"answer": "Response B"}

        await cache.set(message, thread_a, response_a)
        await cache.set(message, thread_b, response_b)

        assert await cache.get(message, thread_a) == response_a
        assert await cache.get(message, thread_b) == response_b

    async def test_completion_cache_key_format(self) -> None:
        """Cache keys follow the expected rag:v1:completion: prefix."""
        valkey = _make_valkey()
        cache = CompletionCache(valkey)
        await cache.set("test message", _THREAD_ID, {"answer": "ok"})
        stored_keys = list(valkey._store.keys())
        assert len(stored_keys) == 1
        assert stored_keys[0].startswith("rag:v1:completion:")

    async def test_set_calls_valkey_set_with_ttl(self) -> None:
        """set() calls ValkeyClient.set() with the correct TTL (86400 s)."""
        valkey = _make_valkey()
        cache = CompletionCache(valkey)
        await cache.set("msg", _THREAD_ID, {"answer": "x"})

        valkey.set.assert_called_once()
        call_kwargs = valkey.set.call_args
        # ttl must be passed as keyword argument
        assert call_kwargs.kwargs.get("ttl") == 86_400
