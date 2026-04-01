"""PollingPolicy entity — adaptive scheduling configuration for market data ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.ids import new_ulid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import DatasetType, Provider

if TYPE_CHECKING:
    from datetime import date, datetime


@dataclass
class PollingPolicy:
    """Defines when and how frequently a provider/symbol/dataset should be polled.

    The effective polling interval is adaptive:
        effective = base_interval_seconds / (1 + k * hotness)
    where hotness ∈ [0.0, 1.0] and k is a scaling factor.

    A policy with symbol=None acts as a wildcard and matches any symbol.
    Higher priority values are processed first (min-heap semantics reversed).
    """

    id: str = field(default_factory=new_ulid)
    provider: Provider = Provider.EODHD
    dataset_type: DatasetType = DatasetType.OHLCV
    symbol: str | None = None
    exchange: str | None = None
    timeframe: str | None = None
    base_interval_seconds: float = 3600.0
    k: float = 1.0
    hotness: float = 0.0
    priority: int = 0
    is_enabled: bool = True
    backfill_enabled: bool = False
    backfill_days: int | None = None
    backfill_start_date: date | datetime | None = None
    created_at: datetime = field(default_factory=utc_now)

    @property
    def effective_interval_seconds(self) -> float:
        """Adaptive interval: base / (1 + k * hotness).

        Higher hotness → shorter interval → more frequent polling.
        """
        return self.base_interval_seconds / (1 + self.k * self.hotness)

    def is_due(self, last_run_at: datetime | None) -> bool:
        """Return True if this policy should be triggered now.

        A policy is due if it has never run (last_run_at is None) or if
        the elapsed time since last run exceeds the effective interval.
        """
        if last_run_at is None:
            return True
        elapsed: float = (utc_now() - last_run_at).total_seconds()  # type: ignore[no-any-return]
        return elapsed >= self.effective_interval_seconds

    def matches(self, symbol: str) -> bool:
        """Return True if this policy applies to the given symbol.

        A policy with symbol=None is a wildcard and matches all symbols.
        """
        return self.symbol is None or self.symbol == symbol

    def __lt__(self, other: object) -> bool:
        """Higher priority value = earlier in the scheduling queue."""
        if not isinstance(other, PollingPolicy):
            return NotImplemented
        return self.priority > other.priority

    def __le__(self, other: object) -> bool:
        if not isinstance(other, PollingPolicy):
            return NotImplemented
        return self.priority >= other.priority

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, PollingPolicy):
            return NotImplemented
        return self.priority < other.priority

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, PollingPolicy):
            return NotImplemented
        return self.priority <= other.priority
