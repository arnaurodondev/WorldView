"""ProviderBudget entity — token-bucket rate-limit tracking for upstream providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from common.ids import new_ulid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.errors import ProviderRateLimited


@dataclass
class ProviderBudget:
    """Token-bucket rate limiter for a single upstream data provider.

    Tokens are consumed on each API call and refill at a fixed rate per second.
    burst_capacity is the maximum number of tokens that can accumulate.
    """

    id: str = field(default_factory=new_ulid)
    provider: Provider = Provider.EODHD
    burst_capacity: float = 1000.0
    refill_rate: float = 10.0
    tokens: float = 1000.0
    last_refill_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def refill(self, elapsed_seconds: float) -> None:
        """Add tokens based on elapsed time, capped at burst_capacity."""
        self.tokens = min(self.burst_capacity, self.tokens + self.refill_rate * elapsed_seconds)
        self.last_refill_at = utc_now()
        self.updated_at = self.last_refill_at

    def try_consume(self, n: float = 1.0) -> bool:
        """Try to consume n tokens. Returns True if successful, False if insufficient."""
        if self.tokens >= n:
            self.tokens -= n
            self.updated_at = utc_now()
            return True
        return False

    def consume(self, n: float = 1.0) -> None:
        """Consume n tokens, raising ProviderRateLimited if the budget is exhausted."""
        if not self.try_consume(n):
            raise ProviderRateLimited(f"Provider {self.provider!r} budget exhausted: need {n}, have {self.tokens:.2f}")

    def time_until_available(self, n: float = 1.0) -> float:
        """Return seconds until n tokens will be available (0.0 if already available)."""
        if self.tokens >= n:
            return 0.0
        deficit = n - self.tokens
        return deficit / self.refill_rate

    # ── Provider default factories ────────────────────────────────────────────

    # EODHD hard daily quota is 100_000 requests/day.  Modelled as a token
    # bucket whose refill rate equals the sustained daily allowance:
    #   100_000 / 86_400 s ≈ 1.157 tokens/second.
    # burst_capacity (10_000) bounds how much a quiet period can bank before a
    # burst, ~2.4 h of allowance.  These values match the live DB row written by
    # migration 0005; the old 1000/10.0 defaults under-provisioned fresh envs by
    # 10x on burst and over-provisioned refill by ~8.6x (BP-EODHD-QUOTA).
    EODHD_BURST_CAPACITY: ClassVar[float] = 10_000.0
    EODHD_REFILL_RATE: ClassVar[float] = 1.157  # 100_000 req/day ÷ 86_400 s

    @classmethod
    def for_eodhd(cls) -> ProviderBudget:
        """EODHD: 10_000-token burst, refills at ~1.157 tokens/second (100k/day)."""
        return cls(
            provider=Provider.EODHD,
            burst_capacity=cls.EODHD_BURST_CAPACITY,
            refill_rate=cls.EODHD_REFILL_RATE,
            tokens=cls.EODHD_BURST_CAPACITY,
        )

    @classmethod
    def for_alpha_vantage(cls) -> ProviderBudget:
        """Alpha Vantage: 5-token burst, refills at ~0.083 tokens/second (5/min)."""
        return cls(provider=Provider.ALPHA_VANTAGE, burst_capacity=5.0, refill_rate=0.083, tokens=5.0)
