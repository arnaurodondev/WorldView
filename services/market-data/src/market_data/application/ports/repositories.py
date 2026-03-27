"""Repository port interfaces (ABCs) for the market-data service.

Each ABC defines the contract between the application layer and the
infrastructure layer.  Concrete implementations live in
``market_data.infrastructure.db.repositories``.

All methods are ``async`` — no synchronous I/O is allowed in the
application layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime

    from market_data.domain.entities import (
        FundamentalsRecord,
        Instrument,
        OHLCVBar,
        Quote,
        Security,
    )
    from market_data.domain.enums import Timeframe
    from market_data.domain.value_objects import InstrumentFlags


class SecurityRepository(ABC):
    """Read/write access to the ``securities`` table."""

    @abstractmethod
    async def find_by_id(self, id: str) -> Security | None:  # noqa: A002
        """Return the security with the given UUID, or ``None``."""

    @abstractmethod
    async def find_by_figi(self, figi: str) -> Security | None:
        """Return the security with the given FIGI, or ``None``."""

    @abstractmethod
    async def find_by_isin(self, isin: str) -> Security | None:
        """Return the security with the given ISIN, or ``None``."""

    @abstractmethod
    async def list(self, limit: int = 100, offset: int = 0) -> tuple[list[Security], int]:
        """Return a paginated slice of all securities and the total count."""

    @abstractmethod
    async def upsert(self, security: Security) -> Security:
        """Insert or update the security; return the persisted record."""


class InstrumentRepository(ABC):
    """Read/write access to the ``instruments`` table."""

    @abstractmethod
    async def find_by_symbol_exchange(self, symbol: str, exchange: str) -> Instrument | None:
        """Return the instrument for the given symbol/exchange pair, or ``None``."""

    @abstractmethod
    async def find_by_id(self, id: str) -> Instrument | None:  # noqa: A002
        """Return the instrument with the given UUID, or ``None``."""

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        has_ohlcv: bool | None = None,
        has_quotes: bool | None = None,
        has_fundamentals: bool | None = None,
        exchange: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Instrument]:
        """Full-text search instruments by symbol or name fragment, with optional DB-side filters."""

    @abstractmethod
    async def count(
        self,
        query: str = "",
        *,
        has_ohlcv: bool | None = None,
        has_quotes: bool | None = None,
        has_fundamentals: bool | None = None,
        exchange: str | None = None,
    ) -> int:
        """Return the total count of instruments matching the given query and filters."""

    @abstractmethod
    async def upsert(self, instrument: Instrument) -> Instrument:
        """Insert or update the instrument; return the persisted record."""

    @abstractmethod
    async def update_flags(self, id: str, flags: InstrumentFlags) -> None:  # noqa: A002
        """Update the capability flags for the instrument identified by ``id``."""

    @abstractmethod
    async def update_metadata(self, id: str, metadata: dict[str, str | None]) -> None:  # noqa: A002
        """Update instrument metadata fields (name, isin, sector, etc.), ignoring None-valued keys."""


class OHLCVRepository(ABC):
    """Read/write access to the ``ohlcv_bars`` hypertable."""

    @abstractmethod
    async def bulk_upsert_with_priority(self, bars: list[OHLCVBar]) -> None:
        """Bulk-upsert bars using provider-priority conflict resolution.

        Uses ``INSERT ... ON CONFLICT (instrument_id, timeframe, bar_date)
        DO UPDATE SET ... WHERE EXCLUDED.provider_priority >=
        ohlcv_bars.provider_priority`` so that lower-priority data never
        overwrites higher-priority stored records.
        """

    @abstractmethod
    async def find_by_instrument_timeframe_range(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[OHLCVBar]:
        """Return bars for the given instrument/timeframe within [start, end]."""

    @abstractmethod
    async def get_available_timeframes(self, instrument_id: str) -> list[Timeframe]:
        """Return all timeframes for which the instrument has stored bars."""

    @abstractmethod
    async def get_date_range(self, instrument_id: str, timeframe: Timeframe) -> tuple[date, date] | None:
        """Return ``(min_date, max_date)`` for the instrument/timeframe, or ``None``."""


class QuoteRepository(ABC):
    """Read/write access to the ``quotes`` table."""

    @abstractmethod
    async def upsert(self, quote: Quote) -> Quote:
        """Insert or replace the latest quote for the instrument."""

    @abstractmethod
    async def find_by_instrument(self, instrument_id: str) -> Quote | None:
        """Return the latest quote for the instrument, or ``None``."""

    @abstractmethod
    async def find_by_instruments(self, ids: list[str]) -> list[Quote]:
        """Return latest quotes for a batch of instrument IDs."""


class FundamentalsRepository(ABC):
    """Read/write access to fundamentals section tables."""

    @abstractmethod
    async def upsert_income_statement(self, record: FundamentalsRecord) -> None:
        """Upsert an income statement record."""

    @abstractmethod
    async def upsert_balance_sheet(self, record: FundamentalsRecord) -> None:
        """Upsert a balance sheet record."""

    @abstractmethod
    async def upsert_cash_flow(self, record: FundamentalsRecord) -> None:
        """Upsert a cash flow statement record."""

    @abstractmethod
    async def upsert_highlights(self, record: FundamentalsRecord) -> None:
        """Upsert highlights (TTM operational metrics). FIX-F10."""

    @abstractmethod
    async def upsert_valuation_ratios(self, record: FundamentalsRecord) -> None:
        """Upsert valuation ratios."""

    @abstractmethod
    async def upsert_technicals_snapshot(self, record: FundamentalsRecord) -> None:
        """Upsert a technicals snapshot."""

    @abstractmethod
    async def upsert_share_statistics(self, record: FundamentalsRecord) -> None:
        """Upsert share statistics."""

    @abstractmethod
    async def upsert_splits_dividends(self, record: FundamentalsRecord) -> None:
        """Upsert splits/dividends data."""

    @abstractmethod
    async def upsert_analyst_consensus(self, record: FundamentalsRecord) -> None:
        """Upsert analyst consensus data."""

    @abstractmethod
    async def upsert_earnings_history(self, record: FundamentalsRecord) -> None:
        """Upsert earnings history."""

    @abstractmethod
    async def upsert_earnings_trend(self, record: FundamentalsRecord) -> None:
        """Upsert earnings trend data."""

    @abstractmethod
    async def upsert_earnings_annual_trend(self, record: FundamentalsRecord) -> None:
        """Upsert annual earnings trend data."""

    @abstractmethod
    async def upsert_dividend_history(self, record: FundamentalsRecord) -> None:
        """Upsert dividend history."""

    @abstractmethod
    async def upsert_outstanding_shares(self, record: FundamentalsRecord) -> None:
        """Upsert outstanding shares data."""

    @abstractmethod
    async def upsert_company_profile(self, record: FundamentalsRecord) -> None:
        """Upsert company profile data. FIX-F4."""

    @abstractmethod
    async def upsert_institutional_holders(self, record: FundamentalsRecord) -> None:
        """Upsert institutional holders data. FIX-F6."""

    @abstractmethod
    async def upsert_fund_holders(self, record: FundamentalsRecord) -> None:
        """Upsert fund holders data. FIX-F6."""

    @abstractmethod
    async def upsert_insider_transactions_snapshot(self, record: FundamentalsRecord) -> None:
        """Upsert embedded insider transactions snapshot. FIX-F7."""

    @abstractmethod
    async def merge_upsert(self, records: list[FundamentalsRecord], instrument_id: str) -> None:
        """Dispatch each record in the list to the correct per-section upsert method."""


class IngestionEventRepository(ABC):
    """Idempotency dedup table for processed Kafka events."""

    @abstractmethod
    async def exists(self, event_id: str) -> bool:
        """Return ``True`` if the event has already been processed."""

    @abstractmethod
    async def exists_by_content_hash(self, sha256: str, event_type: str) -> bool:
        """Return ``True`` if a prior event with the same SHA-256 was already processed.

        Used for data-level deduplication: if the canonical object has not changed
        (same SHA-256), skip re-processing even when the ``event_id`` is new.
        """

    @abstractmethod
    async def create(
        self,
        event_id: str,
        event_type: str | None = None,
        content_sha256: str | None = None,
    ) -> None:
        """Record the event as processed, storing its canonical content hash."""

    @abstractmethod
    async def create_if_not_exists(
        self,
        event_id: str,
        event_type: str | None = None,
        content_sha256: str | None = None,
    ) -> bool:
        """Atomically insert the event if it does not already exist.

        Returns ``True`` if the row was newly created, ``False`` if the event
        was already recorded (duplicate).  This replaces the separate
        ``is_duplicate()`` + ``create()`` pattern with a single atomic
        INSERT … ON CONFLICT DO NOTHING … RETURNING operation, eliminating
        the check-before-insert race condition (BP-035).
        """


class FailedTaskRepository(ABC):
    """Retry queue for consumer processing failures."""

    @abstractmethod
    async def create(self, task_type: str, payload: dict, max_attempts: int = 5) -> str:
        """Persist a new failed task; return the new task ID."""

    @abstractmethod
    async def find_retryable(self, limit: int = 100) -> list[dict]:
        """Return tasks eligible for retry (status=pending, next_attempt_at <= now)."""

    @abstractmethod
    async def increment_attempts(self, task_id: str, next_attempt_at: datetime, last_error: str | None = None) -> None:
        """Increment the attempt counter and schedule the next retry."""

    @abstractmethod
    async def mark_dead(self, task_id: str, last_error: str | None = None) -> None:
        """Mark a task as permanently failed (status=dead_letter)."""


class OutboxEventRepository(ABC):
    """Transactional outbox for domain event publishing."""

    @abstractmethod
    async def create(self, event_type: str, topic: str, payload: dict) -> str:
        """Insert a new pending outbox record; return the new record ID."""

    @abstractmethod
    async def find_pending(self, limit: int = 100) -> list[dict]:
        """Return pending records whose lease has expired or was never set."""

    @abstractmethod
    async def claim(self, event_id: str, worker_id: str, lease_expires_at: datetime) -> bool:
        """Atomically claim the record for this worker; return ``True`` on success."""

    @abstractmethod
    async def mark_dispatched(self, event_id: str) -> None:
        """Mark the record as successfully dispatched."""

    @abstractmethod
    async def release_stale(self, stale_before: datetime) -> int:
        """Release all records whose lease expired before ``stale_before``; return count."""
