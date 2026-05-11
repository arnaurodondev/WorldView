"""Repository port interfaces (ABCs) for the market-data service.

Each ABC defines the contract between the application layer and the
infrastructure layer.  Concrete implementations live in
``market_data.infrastructure.db.repositories``.

All methods are ``async`` — no synchronous I/O is allowed in the
application layer.

Read-side query types (``MetricDataPoint``, ``ScreenFilter``, ``ScreenResult``)
are defined here so the application layer owns the contract that both use
cases and infrastructure implementations depend on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.domain.entities import (
        FundamentalsRecord,
        Instrument,
        OHLCVBar,
        PredictionMarket,
        PredictionMarketSnapshot,
        Quote,
        ScreenFieldMetadata,
        Security,
    )
    from market_data.domain.enums import FundamentalsSection, Timeframe
    from market_data.domain.value_objects import InstrumentFlags

# ── Read-side query result types ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MetricDataPoint:
    """A single timeseries data point from the ``fundamental_metrics`` table."""

    as_of_date: date
    value_numeric: Decimal | None
    value_text: str | None
    period_type: str | None


@dataclass(frozen=True, slots=True)
class ScreenFilter:
    """A single metric filter for instrument screening."""

    metric: str
    min_value: float | None = None
    max_value: float | None = None
    period_type: str | None = None
    sector: str | None = None


@dataclass(frozen=True, slots=True)
class ScreenResult:
    """One instrument matching the screen criteria."""

    instrument_id: str
    metrics: dict[str, Decimal | None]
    ticker: str | None = None
    name: str | None = None
    exchange: str | None = None
    sector: str | None = None


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

    @abstractmethod
    async def update_from_enrichment(self, security_id: str, fields: dict[str, str | None]) -> None:
        """COALESCE-update security fields from enrichment data.

        Only updates columns whose current DB value IS NULL, preserving any
        field already populated by a higher-priority source.  This prevents
        EODHD from overwriting manually-curated or exchange-sourced values.
        """


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

    @abstractmethod
    async def find_by_isin(self, isin: str) -> Instrument | None:
        """Return the first active instrument whose ISIN matches, or ``None``."""

    @abstractmethod
    async def find_by_symbol_icase(self, symbol: str) -> Instrument | None:
        """Return the first active instrument whose symbol matches case-insensitively, or ``None``."""


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

    @abstractmethod
    async def bulk_upsert_derived(self, bars: list[OHLCVBar]) -> None:
        """Upsert derived bars (is_derived=True) unconditionally.

        Derived bars are computed locally from finer-grained bars (e.g. weekly
        aggregated from daily).  They are always overwritten on recalculation
        regardless of provider_priority — the local derivation IS the source of
        truth for these timeframes (PLAN-0036 W2-4).
        """

    @abstractmethod
    async def find_by_instrument_timeframe_datetime_range(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[OHLCVBar]:
        """Return bars for the given datetime range (inclusive on both ends).

        Unlike ``find_by_instrument_timeframe_range`` which accepts ``date``
        boundaries, this method accepts full ``datetime`` objects — required
        for intraday period queries (e.g. 5m/1h resampling windows).
        """

    @abstractmethod
    async def find_derived(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        *,
        limit: int = 200,
    ) -> list[OHLCVBar]:
        """Return derived bars for the given instrument/timeframe, sorted descending.

        Used by ``GetOrDeriveOHLCVBarsUseCase`` to serve pre-computed weekly /
        monthly bars without an EODHD call (PLAN-0036 W2-5).
        """

    @abstractmethod
    async def get_sector_period_returns(self, lookback_days: int) -> list[dict]:
        """Return average period return per sector using daily OHLCV bars.

        Uses calendar-based lookback from the most recent daily bar per instrument
        rather than derived weekly/monthly bars (which are rarely populated).

        lookback_days: 7 for 1W, 30 for 1M
        Returns a list of dicts: {name: str, change_pct: float | None, instrument_count: int}
        """

    @abstractmethod
    async def get_period_movers(
        self,
        lookback_days: int,
        mover_type: str,
        limit: int,
    ) -> list[dict]:
        """Return top gainers or losers sorted by period return using daily OHLCV bars.

        Uses calendar-based lookback from the most recent daily bar per instrument.

        lookback_days: 7 for 1W, 30 for 1M
        mover_type: "gainers" (DESC) or "losers" (ASC)
        Returns list of dicts: {instrument_id, ticker, name, period_return_pct}
        """


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
    async def create(
        self,
        event_type: str,
        topic: str,
        payload: dict,
        partition_key: str | None = None,
    ) -> str:
        """Insert a new pending outbox record; return the new record ID.

        ``partition_key`` (PLAN-0057-followup Wave B / F-DATA-06): optional
        Kafka partition key. When set, the outbox dispatcher will pass
        ``key=partition_key.encode("utf-8")`` to ``producer.produce(...)``
        so that every event for the same key lands on the same Kafka
        partition (preserving per-aggregate ordering for downstream
        consumers). When ``None`` (default), Kafka's sticky/round-robin
        partitioner is used — fine for events with no ordering invariants.
        """

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


# ── Read-side fundamentals query port ────────────────────────────────────────


class FundamentalsReadRepository(ABC):
    """Read-only access to fundamentals section tables.

    Separate from the write-focused ``FundamentalsRepository`` so that read
    operations in the API layer go through a clean port without inheriting the
    13 upsert methods that only belong to the consumer write path.
    """

    @abstractmethod
    async def find_by_section(
        self,
        instrument_id: str,
        section: FundamentalsSection,
    ) -> list[FundamentalsRecord]:
        """Return all fundamentals records for the given instrument and section."""


# ── Read-side fundamental metrics query port ─────────────────────────────────


class FundamentalMetricsQueryRepository(ABC):
    """Read-only query interface for the ``fundamental_metrics`` projection table."""

    @abstractmethod
    async def get_timeseries(
        self,
        instrument_id: str,
        metric: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        period_type: str | None = None,
        limit: int = 1000,
        order: str = "asc",
    ) -> list[MetricDataPoint]:
        """Return timeseries data points for an instrument/metric combination.

        ``order`` is ``"asc"`` (oldest first) or ``"desc"`` (newest first applied
        at the SQL ``LIMIT`` boundary). The implementation must always return
        rows in chronological order regardless of ``order``.
        """

    @abstractmethod
    async def screen(
        self,
        filters: list[ScreenFilter],
        *,
        limit: int = 50,
        offset: int = 0,
        sort_by: str | None = None,
        sort_order: str = "asc",
    ) -> tuple[list[ScreenResult], int]:
        """Screen instruments by metric thresholds; return (matching instruments, total count)."""

    @abstractmethod
    async def get_available_metrics(self, instrument_id: str) -> list[str]:
        """Return all distinct metric names available for an instrument."""

    @abstractmethod
    async def get_screen_field_metadata(self) -> list[ScreenFieldMetadata]:
        """Return all rows from ``screen_field_metadata`` (DB fallback for cache miss)."""


# ── Prediction Market repositories (PRD-0019) ─────────────────────────────────


class PredictionMarketRepository(ABC):
    """Port for prediction market read/write operations."""

    @abstractmethod
    async def upsert(self, market: PredictionMarket) -> PredictionMarket:
        """Insert or update a prediction market record.

        Conflict target: ``market_id``.
        Updates: question, description, outcomes, close_time,
        resolution_status, resolved_answer, updated_at.
        """

    @abstractmethod
    async def find_by_market_id(self, market_id: str) -> PredictionMarket | None:
        """Return the market with the given ``market_id``, or ``None``."""

    @abstractmethod
    async def list_markets(
        self,
        *,
        status: str | None,
        query: str | None,
        limit: int,
        offset: int,
        category: str | None = None,
    ) -> tuple[list[tuple[PredictionMarket, Decimal | None]], int]:
        """Return a paginated list of ``(market, latest_volume_24h)`` pairs and total.

        ``status``: filter by ``resolution_status`` (exact match); ``None`` = all.
        ``query``: filter by ``question ILIKE '%query%'``; ``None`` = all.
        ``category``: filter by ``LOWER(category) = LOWER(:category)`` exact
            match (PLAN-0049 T-C-3-03); ``None`` = all.  Free-form string —
            backend never validates the enum so new Polymarket tags roll out
            without a code change.  NULL-category rows never match.

        ``latest_volume_24h``: ``volume_24h`` from the most recent snapshot
        (``LEFT JOIN LATERAL ... ORDER BY snapshot_at DESC LIMIT 1``); ``None``
        when the market has no snapshots or the latest snapshot has no volume.
        Forward-compatible: callers tolerating ``None`` continue to work.
        """

    @abstractmethod
    async def count_open_by_category(self) -> list[tuple[str | None, int]]:
        """Return ``[(category, count), ...]`` for all currently-open markets.

        PLAN-0053 T-C-3-05. ``category`` may be NULL — frontends typically
        bucket NULL into "uncategorized" or skip it. Counts are computed over
        ``WHERE resolution_status = 'open'`` so unresolved or cancelled
        markets are excluded.

        Order: descending by count (highest first). Forward-compatible: a
        new Polymarket category lights up automatically — no code changes
        needed because we don't validate the enum.
        """


class PredictionMarketSnapshotRepository(ABC):
    """Port for prediction market snapshot (hypertable) operations."""

    @abstractmethod
    async def insert_if_not_exists(self, snapshot: PredictionMarketSnapshot) -> bool:
        """Atomically insert the snapshot; return ``True`` if new, ``False`` on conflict.

        Conflict target: ``(market_id, snapshot_at)``.
        """

    @abstractmethod
    async def list_snapshots(
        self,
        market_id: str,
        *,
        from_dt: datetime | None,
        to_dt: datetime | None,
        limit: int,
    ) -> list[PredictionMarketSnapshot]:
        """Return snapshots for ``market_id``, ordered by ``snapshot_at DESC``."""

    @abstractmethod
    async def get_latest_prices_batch(
        self,
        market_ids: list[str],
    ) -> dict[str, dict[str, float]]:
        """Return the latest ``outcomes_prices`` for each market in ``market_ids``.

        Uses ``DISTINCT ON (market_id)`` ordered by ``snapshot_at DESC`` — a single
        query regardless of how many markets are requested (avoids N+1).

        Returns a dict keyed by ``market_id``; missing markets are not included.
        """
