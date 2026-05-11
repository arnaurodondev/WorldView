"""Unit tests for ValkeyChunkCacheAdapter (T-A-3-02).

Verifies that get/set delegate to ValkeyClient and that TTL
constants have the expected values.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valkey(get_result: dict | None = None) -> AsyncMock:
    valkey = AsyncMock()
    valkey.get_json = AsyncMock(return_value=get_result)
    valkey.set_json = AsyncMock(return_value=None)
    return valkey


# ---------------------------------------------------------------------------
# TTL constants
# ---------------------------------------------------------------------------


class TestValkeyChunkCacheTTLConstants:
    def test_chunk_ttl_is_4_hours(self) -> None:
        """CHUNK_TTL is 4 hours (14400 seconds)."""
        from rag_chat.infrastructure.cache.valkey_chunk_cache import CHUNK_TTL

        assert CHUNK_TTL == 4 * 3600

    def test_summary_ttl_is_24_hours(self) -> None:
        """SUMMARY_TTL is 24 hours (86400 seconds)."""
        from rag_chat.infrastructure.cache.valkey_chunk_cache import SUMMARY_TTL

        assert SUMMARY_TTL == 24 * 3600


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


class TestValkeyChunkCacheAdapterGet:
    async def test_get_delegates_to_valkey_get_json(self) -> None:
        """get() calls valkey.get_json with the given key."""
        from rag_chat.infrastructure.cache.valkey_chunk_cache import ValkeyChunkCacheAdapter

        valkey = _make_valkey(get_result={"chunks": ["a", "b"]})
        cache = ValkeyChunkCacheAdapter(valkey)

        result = await cache.get("cache:key:123")

        valkey.get_json.assert_called_once_with("cache:key:123")
        assert result == {"chunks": ["a", "b"]}

    async def test_get_returns_none_on_cache_miss(self) -> None:
        """Returns None when the key is not in Valkey (cache miss)."""
        from rag_chat.infrastructure.cache.valkey_chunk_cache import ValkeyChunkCacheAdapter

        valkey = _make_valkey(get_result=None)
        cache = ValkeyChunkCacheAdapter(valkey)

        result = await cache.get("missing:key")

        assert result is None

    async def test_get_returns_cached_dict_unchanged(self) -> None:
        """The exact dict stored is returned without transformation."""
        from rag_chat.infrastructure.cache.valkey_chunk_cache import ValkeyChunkCacheAdapter

        payload = {"chunks": [1, 2, 3], "query": "AAPL"}
        valkey = _make_valkey(get_result=payload)
        cache = ValkeyChunkCacheAdapter(valkey)

        result = await cache.get("any:key")

        assert result is payload


# ---------------------------------------------------------------------------
# set()
# ---------------------------------------------------------------------------


class TestValkeyChunkCacheAdapterSet:
    async def test_set_delegates_to_valkey_set_json(self) -> None:
        """set() calls valkey.set_json with key, value, and ttl."""
        from rag_chat.infrastructure.cache.valkey_chunk_cache import ValkeyChunkCacheAdapter

        valkey = _make_valkey()
        cache = ValkeyChunkCacheAdapter(valkey)

        payload = {"data": [1, 2, 3]}
        await cache.set("cache:key:456", payload, ttl=3600)

        valkey.set_json.assert_called_once_with("cache:key:456", payload, ttl=3600)

    async def test_set_passes_chunk_ttl(self) -> None:
        """Callers can pass CHUNK_TTL and it flows through unchanged."""
        from rag_chat.infrastructure.cache.valkey_chunk_cache import CHUNK_TTL, ValkeyChunkCacheAdapter

        valkey = _make_valkey()
        cache = ValkeyChunkCacheAdapter(valkey)

        await cache.set("k", {}, ttl=CHUNK_TTL)

        # ttl is passed as positional or keyword — check either way
        call_args = valkey.set_json.call_args
        ttl_passed = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("ttl")
        assert ttl_passed == CHUNK_TTL

    async def test_set_passes_summary_ttl(self) -> None:
        """Callers can pass SUMMARY_TTL and it flows through unchanged."""
        from rag_chat.infrastructure.cache.valkey_chunk_cache import SUMMARY_TTL, ValkeyChunkCacheAdapter

        valkey = _make_valkey()
        cache = ValkeyChunkCacheAdapter(valkey)

        await cache.set("k", {}, ttl=SUMMARY_TTL)

        call_args = valkey.set_json.call_args
        ttl_passed = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("ttl")
        assert ttl_passed == SUMMARY_TTL

    async def test_set_returns_none(self) -> None:
        """set() returns None (it's a fire-and-forget write)."""
        from rag_chat.infrastructure.cache.valkey_chunk_cache import ValkeyChunkCacheAdapter

        valkey = _make_valkey()
        cache = ValkeyChunkCacheAdapter(valkey)

        result = await cache.set("k", {"x": 1}, ttl=60)

        assert result is None
