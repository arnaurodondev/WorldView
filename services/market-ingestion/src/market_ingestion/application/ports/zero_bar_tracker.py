"""Zero-bar tracker port interface.

Tracks consecutive zero-bar API responses per (provider, symbol, timeframe,
dataset_type) tuple.  Used by ExecuteTaskUseCase to decide when to failover
to the next provider in the priority chain.

Zero-bar responses are not errors (e.g., weekend, holiday, new listing), so
the circuit breaker doesn't apply --- this tracker handles soft data-quality
signals separately.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar


class ZeroBarTrackerPort(ABC):
    """Tracks consecutive zero-bar API responses per provider/symbol/timeframe/dataset."""

    FAILOVER_THRESHOLD: ClassVar[int] = 5

    @abstractmethod
    async def record_zero(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> int:
        """Record a zero-bar result. Returns new consecutive streak count."""

    @abstractmethod
    async def reset(self, provider: str, symbol: str, timeframe: str, dataset_type: str) -> None:
        """Reset the zero-bar streak after a successful non-zero fetch."""

    def should_failover(self, streak: int) -> bool:
        """Return True when streak has reached FAILOVER_THRESHOLD."""
        return streak >= self.FAILOVER_THRESHOLD
