"""IngestionTask entity — work item for the market data ingestion pipeline."""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from common.ids import new_ulid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import DatasetType, FundamentalsVariant, IngestionTaskStatus, Provider
from market_ingestion.domain.errors import DomainError, InvalidStateTransition

if TYPE_CHECKING:
    from market_ingestion.domain.value_objects import DateRange, ObjectRef, Timeframe


@dataclass
class IngestionTask:
    """Work item representing a single market data fetch job.

    State machine: PENDING → RUNNING → SUCCEEDED
                                    ↘ RETRY (up to MAX_ATTEMPTS) → FAILED
                                    ↘ FAILED (immediate via fail())
    """

    BASE_BACKOFF_SECONDS: ClassVar[float] = 60.0
    MAX_BACKOFF_SECONDS: ClassVar[float] = 3600.0
    JITTER_FACTOR: ClassVar[float] = 0.20
    MAX_ATTEMPTS: ClassVar[int] = 5

    # Identity
    id: str = field(default_factory=new_ulid)
    provider: Provider = Provider.EODHD
    dataset_type: DatasetType = DatasetType.OHLCV
    symbol: str = ""
    exchange: str | None = None
    timeframe: str | None = None
    variant: str | None = None
    range_start: datetime | None = None
    range_end: datetime | None = None
    dedupe_key: str = ""

    # State machine
    status: IngestionTaskStatus = IngestionTaskStatus.PENDING

    # Lease
    lease_owner: str | None = None
    lease_expires: datetime | None = None

    # Retry
    attempt_count: int = 0
    error_message: str | None = None
    next_attempt_at: datetime | None = None

    # Result
    result_ref: ObjectRef | None = None

    # Audit
    created_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None

    # ── State transitions ────────────────────────────────────────────────────

    def claim(self, worker_id: str, lease_seconds: int = 300) -> None:
        """Transition PENDING or RETRY → RUNNING with a worker lease."""
        if self.status not in (IngestionTaskStatus.PENDING, IngestionTaskStatus.RETRY):
            raise InvalidStateTransition(f"Cannot claim task in status {self.status!r}; must be PENDING or RETRY")
        self.status = IngestionTaskStatus.RUNNING
        self.lease_owner = worker_id
        self.lease_expires = utc_now() + timedelta(seconds=lease_seconds)
        self.attempt_count += 1

    def succeed(self, result_ref: ObjectRef) -> None:
        """Transition RUNNING → SUCCEEDED with a canonical object reference."""
        if self.status != IngestionTaskStatus.RUNNING:
            raise InvalidStateTransition(f"Cannot succeed task in status {self.status!r}; must be RUNNING")
        self.status = IngestionTaskStatus.SUCCEEDED
        self.result_ref = result_ref
        self.completed_at = utc_now()
        self.lease_owner = None
        self.lease_expires = None

    def retry(self, error: Exception) -> None:
        """Transition RUNNING → RETRY, or → FAILED if max attempts reached."""
        if self.status != IngestionTaskStatus.RUNNING:
            raise InvalidStateTransition(f"Cannot retry task in status {self.status!r}; must be RUNNING")
        self.error_message = str(error)
        self.lease_owner = None
        self.lease_expires = None
        if self.attempt_count >= self.MAX_ATTEMPTS:
            self.status = IngestionTaskStatus.FAILED
            self.completed_at = utc_now()
        else:
            self.status = IngestionTaskStatus.RETRY
            backoff = self._calculate_backoff()
            self.next_attempt_at = utc_now() + timedelta(seconds=backoff)

    def fail(self, error: Exception) -> None:
        """Transition RUNNING → FAILED unconditionally (non-retriable error)."""
        if self.status != IngestionTaskStatus.RUNNING:
            raise InvalidStateTransition(f"Cannot fail task in status {self.status!r}; must be RUNNING")
        self.status = IngestionTaskStatus.FAILED
        self.error_message = str(error)
        self.completed_at = utc_now()
        self.lease_owner = None
        self.lease_expires = None

    # ── Queries ──────────────────────────────────────────────────────────────

    def is_lease_expired(self) -> bool:
        """Return True if the current lease has passed its expiry time."""
        if self.lease_expires is None:
            return False
        return utc_now() > self.lease_expires  # type: ignore[no-any-return]

    # ── Internals ────────────────────────────────────────────────────────────

    def _calculate_backoff(self) -> float:
        """Exponential backoff with ±20% jitter, capped at MAX_BACKOFF_SECONDS.

        Formula: BASE * 2^(attempt_count - 1), then ±JITTER_FACTOR random jitter.
        """
        raw = self.BASE_BACKOFF_SECONDS * math.pow(2, self.attempt_count - 1)
        capped = min(raw, self.MAX_BACKOFF_SECONDS)
        jitter = capped * self.JITTER_FACTOR * (random.random() * 2 - 1)  # noqa: S311
        return max(0.0, capped + jitter)

    @staticmethod
    def _build_dedupe_key(
        provider: Provider,
        dataset_type: DatasetType,
        symbol: str,
        timeframe: str | None,
        range_start: datetime | None,
        range_end: datetime | None,
    ) -> str:
        range_hash = hashlib.sha256(f"{range_start}:{range_end}".encode()).hexdigest()[:16]
        tf = timeframe or "none"
        return f"{provider}:{dataset_type}:{symbol}:{tf}:{range_hash}"

    # ── Factory class methods ─────────────────────────────────────────────────

    @classmethod
    def create_ohlcv_task(
        cls,
        provider: Provider,
        symbol: str,
        timeframe: Timeframe,
        date_range: DateRange,
        exchange: str | None = None,
    ) -> IngestionTask:
        """Create an OHLCV ingestion task."""
        task = cls(
            provider=provider,
            dataset_type=DatasetType.OHLCV,
            symbol=symbol,
            exchange=exchange,
            timeframe=str(timeframe),
            range_start=date_range.start,
            range_end=date_range.end,
        )
        task.dedupe_key = cls._build_dedupe_key(
            provider, DatasetType.OHLCV, symbol, str(timeframe), date_range.start, date_range.end
        )
        return task

    @classmethod
    def create_quote_task(
        cls,
        provider: Provider,
        symbol: str,
        date_range: DateRange,
        exchange: str | None = None,
    ) -> IngestionTask:
        """Create a quotes ingestion task."""
        task = cls(
            provider=provider,
            dataset_type=DatasetType.QUOTES,
            symbol=symbol,
            exchange=exchange,
            range_start=date_range.start,
            range_end=date_range.end,
        )
        task.dedupe_key = cls._build_dedupe_key(
            provider, DatasetType.QUOTES, symbol, None, date_range.start, date_range.end
        )
        return task

    @classmethod
    def create_fundamentals_task(
        cls,
        provider: Provider,
        symbol: str,
        variant: FundamentalsVariant,
        date_range: DateRange,
        exchange: str | None = None,
    ) -> IngestionTask:
        """Create a fundamentals ingestion task."""
        task = cls(
            provider=provider,
            dataset_type=DatasetType.FUNDAMENTALS,
            symbol=symbol,
            exchange=exchange,
            variant=variant.value,
            range_start=date_range.start,
            range_end=date_range.end,
        )
        task.dedupe_key = cls._build_dedupe_key(
            provider, DatasetType.FUNDAMENTALS, symbol, None, date_range.start, date_range.end
        )
        return task


def exceeds_max_attempts(task: IngestionTask) -> bool:
    """True if the task has consumed all allowed retry attempts."""
    return task.attempt_count >= IngestionTask.MAX_ATTEMPTS and task.status == IngestionTaskStatus.FAILED


def raise_if_exhausted(task: IngestionTask) -> None:
    """Raise DomainError if the task cannot be retried further."""
    if task.status == IngestionTaskStatus.FAILED:
        raise DomainError(
            f"Task {task.id} is permanently FAILED after {task.attempt_count} attempt(s): {task.error_message}"
        )
