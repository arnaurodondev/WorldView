"""Cache-aside wrapper for quote data using Valkey."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from market_data.api.schemas.quotes import QuoteResponse
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class QuoteCache:
    """Cache-aside wrapper for quote data using Valkey.

    Key format: ``quote:v1:{instrument_id}``
    TTL: 5 seconds by default (configurable).
    """

    _KEY_PREFIX = "quote:v1"
    _DEFAULT_TTL = 5

    def __init__(self, client: ValkeyClient) -> None:
        self._client = client

    def _key(self, instrument_id: str) -> str:
        return f"{self._KEY_PREFIX}:{instrument_id}"

    async def get(self, instrument_id: str) -> QuoteResponse | None:
        """Return cached QuoteResponse or ``None`` on cache miss or connection error."""
        from redis.asyncio import ConnectionError as RedisConnectionError  # type: ignore[import-untyped]

        key = self._key(instrument_id)
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            from market_data.api.schemas.quotes import QuoteResponse

            return QuoteResponse.model_validate_json(raw)
        except RedisConnectionError:
            logger.warning("quote_cache_unavailable_get", key=key)
            return None

    async def set(self, instrument_id: str, quote: QuoteResponse, ttl: int = _DEFAULT_TTL) -> None:
        """Cache a QuoteResponse; silently degrades on connection error."""
        from redis.asyncio import ConnectionError as RedisConnectionError  # type: ignore[import-untyped]

        key = self._key(instrument_id)
        try:
            await self._client.set(key, quote.model_dump_json(), ttl=ttl)
        except RedisConnectionError:
            logger.warning("quote_cache_unavailable_set", key=key)

    async def invalidate(self, instrument_id: str) -> None:
        """Remove the cached quote for the given instrument."""
        from redis.asyncio import ConnectionError as RedisConnectionError  # type: ignore[import-untyped]

        key = self._key(instrument_id)
        try:
            await self._client.delete(key)
        except RedisConnectionError:
            logger.warning("quote_cache_unavailable_invalidate", key=key)

    async def invalidate_many(self, instrument_ids: list[str]) -> None:
        """Remove cached quotes for multiple instruments."""
        from redis.asyncio import ConnectionError as RedisConnectionError  # type: ignore[import-untyped]

        keys = [self._key(iid) for iid in instrument_ids]
        try:
            await self._client.delete_many(keys)
        except RedisConnectionError:
            logger.warning("quote_cache_unavailable_invalidate_many", count=len(keys))
