"""Domain value objects for the Content Ingestion service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import common.time


@dataclass
class TokenBucket:
    """Token-bucket rate limiter (NOT thread-safe; use one instance per adapter).

    Args:
        capacity: Maximum number of tokens the bucket can hold.
        tokens: Current token count (float to allow fractional accumulation).
        refill_rate: Tokens added per second.
        last_refill: UTC datetime of the last refill calculation.
    """

    capacity: int
    tokens: float
    refill_rate: float
    last_refill: datetime

    def _refill(self) -> None:
        now = common.time.utc_now()
        elapsed = (now - self.last_refill).total_seconds()
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, n: int = 1) -> bool:
        """Attempt to consume *n* tokens.

        Returns:
            True if tokens were available and consumed; False if the bucket
            does not have enough tokens.
        """
        self._refill()
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def wait_time(self, n: int = 1) -> float:
        """Return the number of seconds to wait before *n* tokens are available.

        Returns:
            0.0 if tokens are already available; positive float otherwise.
        """
        self._refill()
        if self.tokens >= n:
            return 0.0
        return (n - self.tokens) / self.refill_rate
