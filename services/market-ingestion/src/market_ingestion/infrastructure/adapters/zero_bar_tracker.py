"""Valkey-backed zero-bar streak counter.

Key schema: ``s2:v1:zerobar:{provider}:{symbol}:{timeframe}:{dataset_type}``
TTL: 86400 seconds (24h) --- stale streaks from weekends auto-expire.

Thread-safe: INCR is atomic in Valkey. Last-writer-wins for concurrent
resets is acceptable (matches circuit breaker design philosophy).

F-003: INCR + EXPIRE are executed in a single pipeline (MULTI/EXEC) to
       guarantee atomicity — a crash between the two cannot leave a key
       without a TTL (which would leak memory).
F-014: Key prefix follows the ADR-0004 taxonomy: ``<scope>:<version>:<resource>``.
F-016: Empty timeframe is normalised to ``"none"`` to avoid double-colon keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_ingestion.application.ports.zero_bar_tracker import ZeroBarTrackerPort

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]


class ValkeyZeroBarTracker(ZeroBarTrackerPort):
    """Valkey-backed implementation of the zero-bar streak tracker."""

    _KEY_PREFIX: str = "s2:v1:zerobar"
    _STREAK_TTL: int = 86_400  # 24h

    def __init__(self, valkey: ValkeyClient) -> None:
        self._valkey = valkey

    def _key(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> str:
        # F-016: normalise empty/missing timeframe to "none" so the key never
        # contains a ``::`` segment (e.g. ``s2:v1:zerobar:eodhd:AAPL::ohlcv``).
        return f"{self._KEY_PREFIX}:{provider}:{symbol}:{timeframe or 'none'}:{dataset_type}"

    async def record_zero(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> int:
        """Increment the zero-bar streak and refresh its TTL atomically.

        Uses a MULTI/EXEC pipeline so INCR and EXPIRE are applied as a
        single atomic unit — a crash between commands cannot leave a key
        without a TTL.
        """
        key = self._key(provider, symbol, timeframe, dataset_type)
        async with self._valkey.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self._STREAK_TTL)
            results = await pipe.execute()
        # results[0] = new counter value from INCR
        return int(results[0])

    async def reset(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> None:
        """Delete the streak key after a successful non-zero fetch."""
        key = self._key(provider, symbol, timeframe, dataset_type)
        await self._valkey.delete(key)
