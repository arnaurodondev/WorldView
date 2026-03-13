"""Watermark entity — tracks ingestion progress and enables deduplication."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.ids import new_ulid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import BackfillStatus
from market_ingestion.domain.errors import InvalidStateTransition, WatermarkViolation

if TYPE_CHECKING:
    from datetime import datetime


@dataclass
class Watermark:
    """Tracks the high-water mark for a provider/dataset/symbol combination.

    Natural key (6-tuple): (provider, dataset_type, variant, symbol, exchange, timeframe).
    The current_bar_ts advances monotonically — any regression raises WatermarkViolation.
    SHA-256 content_hash supports deduplication of unchanged datasets.
    Backfill state machine: PENDING → IN_PROGRESS → COMPLETED.
    """

    id: str = field(default_factory=new_ulid)
    provider: str = ""
    dataset_type: str = ""
    variant: str | None = None
    symbol: str = ""
    exchange: str | None = None
    timeframe: str | None = None
    current_bar_ts: datetime | None = None
    content_hash: str | None = None
    backfill_status: BackfillStatus = BackfillStatus.PENDING
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def natural_key(self) -> tuple[str, str, str | None, str, str | None, str | None]:
        """The 6-tuple natural key: (provider, dataset_type, variant, symbol, exchange, timeframe)."""
        return (self.provider, self.dataset_type, self.variant, self.symbol, self.exchange, self.timeframe)

    def advance_bar_ts(self, new_ts: datetime) -> None:
        """Advance the bar timestamp monotonically.

        Raises WatermarkViolation if new_ts is not strictly after the current bar_ts.
        """
        if self.current_bar_ts is not None and new_ts <= self.current_bar_ts:
            raise WatermarkViolation(
                f"Cannot advance bar_ts: {new_ts!r} is not strictly after current {self.current_bar_ts!r}"
            )
        self.current_bar_ts = new_ts
        self.updated_at = utc_now()

    def has_changed(self, new_hash: str) -> bool:
        """Return True if the new SHA-256 hash differs from the stored content_hash."""
        return new_hash != self.content_hash

    def start_backfill(self) -> None:
        """Transition backfill status: PENDING → IN_PROGRESS."""
        if self.backfill_status != BackfillStatus.PENDING:
            raise InvalidStateTransition(f"Cannot start backfill from status {self.backfill_status!r}; must be PENDING")
        self.backfill_status = BackfillStatus.IN_PROGRESS
        self.updated_at = utc_now()

    def complete_backfill(self) -> None:
        """Transition backfill status: IN_PROGRESS → COMPLETED."""
        if self.backfill_status != BackfillStatus.IN_PROGRESS:
            raise InvalidStateTransition(
                f"Cannot complete backfill from status {self.backfill_status!r}; must be IN_PROGRESS"
            )
        self.backfill_status = BackfillStatus.COMPLETED
        self.updated_at = utc_now()
