"""Valkey-backed zero-bar streak counter.

Key schema: ``neg:prov:{provider}:{symbol}:{timeframe}:{dataset_type}:zbs``
TTL: 86400 seconds (24h) --- stale streaks from weekends auto-expire.

Thread-safe: INCR is atomic in Valkey. Last-writer-wins for concurrent
resets is acceptable (matches circuit breaker design philosophy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_ingestion.application.ports.zero_bar_tracker import ZeroBarTrackerPort

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]


class ValkeyZeroBarTracker(ZeroBarTrackerPort):
    """Valkey-backed implementation of the zero-bar streak tracker."""

    _KEY_PREFIX: str = "neg:prov"
    _STREAK_TTL: int = 86_400  # 24h

    def __init__(self, valkey: ValkeyClient) -> None:
        self._valkey = valkey

    def _key(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> str:
        return f"{self._KEY_PREFIX}:{provider}:{symbol}:{timeframe}:{dataset_type}:zbs"

    async def record_zero(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> int:
        """Increment the zero-bar streak and refresh its TTL."""
        key = self._key(provider, symbol, timeframe, dataset_type)
        streak = await self._valkey.incr(key)
        await self._valkey.expire(key, self._STREAK_TTL)
        return int(streak)

    async def reset(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> None:
        """Delete the streak key after a successful non-zero fetch."""
        key = self._key(provider, symbol, timeframe, dataset_type)
        await self._valkey.delete(key)
