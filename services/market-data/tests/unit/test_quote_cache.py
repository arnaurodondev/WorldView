"""Unit tests for QuoteCache (MD-026)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from market_data.api.schemas.quotes import QuoteResponse
from market_data.infrastructure.cache.quote_cache import QuoteCache

pytestmark = pytest.mark.unit


def _make_quote_response(instrument_id: str = "instr-001") -> QuoteResponse:
    return QuoteResponse(
        instrument_id=instrument_id,
        bid="309.90",
        ask="310.10",
        last="310.00",
        volume=2_000_000,
        timestamp=datetime(2024, 3, 15, 14, 30, tzinfo=UTC),
        updated_at=datetime(2024, 3, 15, 14, 30, tzinfo=UTC),
    )


def _make_cache(mock_client: AsyncMock) -> QuoteCache:
    cache = QuoteCache.__new__(QuoteCache)
    cache._client = mock_client
    return cache


def test_key_format() -> None:
    """Cache key must use versioned format quote:v1:{instrument_id}."""
    cache = _make_cache(AsyncMock())
    assert cache._key("abc-123") == "quote:v1:abc-123"
    assert cache._key("some-uuid") == "quote:v1:some-uuid"


@pytest.mark.asyncio
async def test_get_returns_none_on_cache_miss() -> None:
    """get() returns None when the key is absent."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=None)
    cache = _make_cache(mock_client)

    result = await cache.get("instr-001")
    assert result is None


@pytest.mark.asyncio
async def test_get_returns_response_on_cache_hit() -> None:
    """get() deserialises a cached QuoteResponse."""
    quote = _make_quote_response()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=quote.model_dump_json())
    cache = _make_cache(mock_client)

    result = await cache.get("instr-001")
    assert result is not None
    assert result.instrument_id == "instr-001"
    assert result.bid == "309.90"


@pytest.mark.asyncio
async def test_set_stores_json_with_ttl() -> None:
    """set() serialises the response and stores it with the default TTL."""
    mock_client = AsyncMock()
    mock_client.set = AsyncMock()
    cache = _make_cache(mock_client)

    quote = _make_quote_response()
    await cache.set("instr-001", quote)

    mock_client.set.assert_awaited_once()
    call_args = mock_client.set.call_args
    key = call_args[0][0]
    value = call_args[0][1]
    ttl = call_args[1].get("ttl")
    assert key == "quote:v1:instr-001"
    assert "309.90" in value
    assert ttl == QuoteCache._DEFAULT_TTL


@pytest.mark.asyncio
async def test_invalidate_deletes_key() -> None:
    """invalidate() calls delete on the correct key."""
    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(return_value=1)
    cache = _make_cache(mock_client)

    await cache.invalidate("instr-001")
    mock_client.delete.assert_awaited_once_with("quote:v1:instr-001")


@pytest.mark.asyncio
async def test_get_degrades_gracefully_on_connection_error() -> None:
    """get() returns None instead of raising on Valkey connection error."""
    from redis.asyncio import ConnectionError as RedisConnectionError  # type: ignore[import-untyped]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=RedisConnectionError("down"))
    cache = _make_cache(mock_client)

    result = await cache.get("instr-001")
    assert result is None  # graceful degradation
