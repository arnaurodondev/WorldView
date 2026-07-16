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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from market_data.domain.entities import (
        FundamentalsRecord,
        Instrument,
        OHLCVBar,
        PredictionEvent,
        PredictionMarket,
        PredictionMarketOI,
        PredictionMarketPrice,
        PredictionMarketSnapshot,
        PredictionMarketTrade,
        Quote,
        ScreenFieldMetadata,
        Security,
    )
    from market_data.domain.enums import FundamentalsSection, PeriodType, Timeframe
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
    """A single metric filter for instrument screening.

    ``metric`` is OPTIONAL (2026-06-28, CAT-B B1 fix): a filter may carry only
    an instrument attribute (sector/industry/country/exchange/has_*) or a
    snapshot-column range with no ``fundamental_metrics`` threshold. The query
    layer routes such attribute-only filters through the no-metric branch (which
    applies the attribute WHERE predicates against ``instruments`` and supports
    ``sort_by``) instead of building a per-metric subquery. See
    ``ScreenFilterRequest`` for why this matters (top-N-by-market-cap queries).
    """

    metric: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    period_type: str | None = None
    sector: str | None = None
    # FIX-LIVE-M (2026-05-24): industry filter (GICS taxonomy). NVDA/AMD/AVGO
    # are sector=Technology, industry=Semiconductors — sector alone is too broad
    # for "AI chip" / "semiconductor" queries from the screen_universe tool.
    industry: str | None = None
    # Wave L-1: instrument-attribute filters (non-metric, WHERE on instruments table)
    country: str | None = None
    exchange: str | None = None
    has_fundamentals: bool | None = None
    has_ohlcv: bool | None = None
    # Wave L-2: instrument_fundamentals_snapshot column filters.
    # Numeric min/max (inclusive) for the six snapshot metrics; equality/IN
    # for credit_rating (string). All fields default to None so existing
    # callers keep working (R11 forward-compat).
    # Applied as WHERE predicates against the LEFT-JOINed snapshot table —
    # ``... WHERE snapshot.eps_ttm >= :min AND snapshot.eps_ttm <= :max``.
    # NULL snapshots (no row for instrument) fail every numeric predicate
    # because PostgreSQL ``NULL >= :v`` evaluates to UNKNOWN, so instruments
    # without a snapshot are correctly excluded when any L-2 filter is active.
    avg_volume_30d_min: float | None = None
    avg_volume_30d_max: float | None = None
    eps_ttm_min: float | None = None
    eps_ttm_max: float | None = None
    free_cash_flow_min: float | None = None
    free_cash_flow_max: float | None = None
    fcf_margin_min: float | None = None
    fcf_margin_max: float | None = None
    interest_coverage_min: float | None = None
    interest_coverage_max: float | None = None
    net_debt_to_ebitda_min: float | None = None
    net_debt_to_ebitda_max: float | None = None
    # credit_rating accepts a list of rating strings (IN predicate) —
    # callers can pass ["AAA", "AA+", "AA", "AA-"] to filter "AA-bracket
    # or better". Empty list / None = no filter. Tuples accepted to allow
    # frozen-dataclass usage from Pydantic mode='python'.
    credit_ratings: tuple[str, ...] | None = None
    # ── Wave L-4a snapshot column filters (PLAN-0089) ────────────────────────
    # Numeric min/max ranges against the four columns added by migration 025.
    # ``institutional_ownership_pct`` and ``short_percent`` are stored as
    # decimal fractions (0.0-1.0+), matching ``fcf_margin``; callers should
    # send fractional values (e.g. 0.5 for "≥50% institutional"). Same
    # NULL-safe semantics as L-2: instruments without a snapshot row drop
    # out as soon as any L-4a predicate is active (``NULL >= :v`` → UNKNOWN).
    analyst_target_price_min: float | None = None
    analyst_target_price_max: float | None = None
    analyst_consensus_rating_min: float | None = None
    analyst_consensus_rating_max: float | None = None
    institutional_ownership_pct_min: float | None = None
    institutional_ownership_pct_max: float | None = None
    short_percent_min: float | None = None
    short_percent_max: float | None = None
    # Wave L-5c: calendar (date) field filters. "Within N days" maps to
    # ``WHERE col BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL ':n days'``
    # against the LEFT-JOINed snapshot. NULL snapshots are correctly excluded
    # because PostgreSQL ``NULL BETWEEN ...`` evaluates to UNKNOWN. Range
    # validation lives at the Pydantic schema layer (ge=0, le=365).
    next_earnings_within_days: int | None = None
    next_dividend_within_days: int | None = None
    # Wave L-4b: insider 90d rollup range filter — negatives are valid.
    insider_net_buy_90d_min: float | None = None
    insider_net_buy_90d_max: float | None = None
    # ── Wave L-5b: intelligence rollup column filters (PLAN-0089) ────────────
    # Numeric min/max ranges for the 4 numeric intelligence fields; boolean
    # equality for the 2 flag fields. All default to None for R11 forward-compat.
    # NULL-safe semantics: instruments without a snapshot row (or with NULL
    # intelligence columns) are excluded when any L-5b predicate is active
    # (``NULL >= :v`` → UNKNOWN). The sync worker fills them nightly.
    news_count_7d_min: int | None = None
    news_count_7d_max: int | None = None
    llm_relevance_7d_max_min: float | None = None
    llm_relevance_7d_max_max: float | None = None
    display_relevance_7d_weighted_min: float | None = None
    display_relevance_7d_weighted_max: float | None = None
    recent_contradiction_count_min: int | None = None
    recent_contradiction_count_max: int | None = None
    has_active_alert: bool | None = None
    has_ai_brief: bool | None = None


@dataclass(frozen=True, slots=True)
class ScreenResult:
    """One instrument matching the screen criteria."""

    instrument_id: str
    metrics: dict[str, Any]
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
    async def touch_fundamentals_ingest_at(self, id: str, ts: datetime) -> None:  # noqa: A002
        """Update ``last_fundamentals_ingest_at`` for the instrument identified by ``id``.

        PLAN-0096 T-W1-02 / BP-545: the FundamentalsConsumer calls this on
        every successful section materialisation (same UoW, no outbox) so the
        column reflects the most-recent successful ingest time. Operators
        query the column to identify stale tickers.
        """

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
        *,
        limit: int | None = None,
    ) -> list[OHLCVBar]:
        """Return bars for the given instrument/timeframe within [start, end].

        When ``limit`` is set, the query uses ``ORDER BY bar_date DESC LIMIT N``
        and reverses the result — so callers always receive the *most-recent* N
        bars in the window rather than the oldest N (matching financial-chart
        conventions).  This pushes the cut-off to the database instead of
        fetching the full window and slicing in Python.

        When ``limit`` is ``None`` (default), all matching bars are returned
        ordered ascending (original behaviour — backward-compatible).
        """

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
        Returns a list of dicts: {name: str, change_pct: float | None, instrument_count: int,
        top_mover_ticker: str | None, top_mover_return_pct: float | None}
        (top mover = largest absolute period return within the sector; 2026-06-10)
        """

    @abstractmethod
    async def get_period_movers(
        self,
        lookback_days: int,
        mover_type: str,
        limit: int,
        offset: int = 0,
    ) -> list[dict]:
        """Return top gainers or losers sorted by period return using daily OHLCV bars.

        Uses calendar-based lookback from the most recent daily bar per instrument.

        lookback_days: 7 for 1W, 30 for 1M
        mover_type: "gainers" (DESC) or "losers" (ASC)
        offset: SQL OFFSET for paginating through the universe leaderboard
        Returns list of dicts: {instrument_id, ticker, name, last_price, period_return_pct}
        (last_price = latest daily close, added 2026-06-10 so consumers don't
        need a second /internal/v1/price batch call)
        """


class QuoteRepository(ABC):
    """Read/write access to the ``quotes`` table."""

    @abstractmethod
    async def upsert(self, quote: Quote) -> Quote:
        """Insert or replace the latest quote for the instrument."""

    @abstractmethod
    async def upsert_if_newer(self, quote: Quote) -> bool:
        """Upsert only if the incoming quote timestamp is newer than the stored row.

        Out-of-order / batch-replay protection for the OHLCV 1m write-through
        (Option B).  Returns True if a row was inserted or updated, False when
        the existing row was newer (no-op).
        """

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

    async def create_many_if_not_exists(
        self,
        events: list[tuple[str, str | None, str | None]],
    ) -> set[str]:
        """Bulk-insert events; return the set of event_ids that were NEW.

        Multi-row ``INSERT … ON CONFLICT DO NOTHING … RETURNING event_id`` so a
        batch consumer can dedup a whole batch in ONE round-trip. Duplicates are
        absent from the returned set. Each tuple is
        ``(event_id, event_type, content_sha256)``.

        Default implementation raises so only adapters that support batching
        need to provide it (opt-in, keeps the port back-compatible).
        """
        raise NotImplementedError


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
        period_type: PeriodType | None = None,
    ) -> list[FundamentalsRecord]:
        """Return all fundamentals records for the given instrument and section.

        PLAN-0095 T-W1-01: ``period_type`` is an optional periodicity filter.
        When supplied, only rows whose ``period_type`` column matches the given
        value are returned. Default ``None`` preserves backward compatibility
        and returns all periodicities (the original behaviour).

        WHY this matters: income_statement / balance_sheet / cash_flow tables
        store both QUARTERLY and ANNUAL rows at the same ``period_end_date``;
        without this filter callers that want one periodicity can silently
        receive the other (BP-559, AMD/NVDA Q1 numbers 4-5x too large).
        """


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

    async def bulk_upsert(self, markets: list[PredictionMarket]) -> None:
        """Insert-or-update many markets in ONE multi-row statement.

        Same conflict target (``market_id``) and COALESCE update policy as
        :meth:`upsert`. Used by the batched consumer to amortise per-message DB
        round-trips. Default raises so only batching adapters implement it.
        """
        raise NotImplementedError

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
        volume_window_days: int | None = None,
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

        ``volume_window_days`` (PLAN-0056 QA): when a positive int, bound the
        latest-snapshot LATERAL to ``snapshot_at >= now() - N days`` so the
        TimescaleDB hypertable prunes to recent chunks instead of descending
        every chunk per market (which cold-scans ~1.8M rows and 500s the
        endpoint under load). Markets with no in-window snapshot get
        ``latest_volume_24h = None`` and sort to the bottom (stale volume must
        not float a dead market to the top). ``None`` / ``<= 0`` = unbounded.
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

    async def bulk_insert_if_not_exists(self, snapshots: list[PredictionMarketSnapshot]) -> int:
        """Insert many snapshots in ONE multi-row ``ON CONFLICT DO NOTHING``.

        Conflict target: ``(market_id, snapshot_at)``. Returns the number of
        rows actually inserted (conflicts skipped). Default raises so only
        batching adapters implement it.
        """
        raise NotImplementedError

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
    async def get_earliest_snapshot_at_or_after(
        self,
        market_id: str,
        at_or_after: datetime,
    ) -> PredictionMarketSnapshot | None:
        """Return the earliest snapshot for ``market_id`` with ``snapshot_at >= at_or_after``.

        Used by the move detector to obtain the TRUE window-start baseline: a
        ``list_snapshots(limit=N)`` scan only returns the newest ``N`` rows, so
        its oldest element is not the window start once a market has more than
        ``N`` snapshots in the window. This single ``ORDER BY snapshot_at ASC
        LIMIT 1`` read returns the genuine earliest-in-window row (or ``None`` if
        the market has no snapshot in the window).
        """

    @abstractmethod
    async def get_latest_prices_batch(
        self,
        market_ids: list[str],
        *,
        window_days: int | None = None,
    ) -> dict[str, dict[str, float]]:
        """Return the latest ``outcomes_prices`` for each market in ``market_ids``.

        Uses ``DISTINCT ON (market_id)`` ordered by ``snapshot_at DESC`` — a single
        query regardless of how many markets are requested (avoids N+1).

        Returns a dict keyed by ``market_id``; missing markets are not included.

        ``window_days`` (PLAN-0056 QA): when a positive int, bound the scan to
        ``snapshot_at >= now() - N days`` so the TimescaleDB hypertable prunes to
        recent chunks instead of ``DISTINCT ON``-SkipScanning every chunk per
        market (a cold second contributor to the list-endpoint pool exhaustion).
        Kept in lock-step with the list use case's ``volume_window_days`` so a
        market's row shows prices from the SAME recent-window snapshot that
        produced its ``volume_24h``; a market with no in-window snapshot is
        simply omitted (its row already carries ``volume_24h=None`` and sorts
        last).  ``None`` / ``<= 0`` = unbounded (legacy behaviour).
        """


class PredictionMarketPricesRepository(ABC):
    """Port for per-token interval price history (hypertable) operations (PLAN-0056 A2)."""

    @abstractmethod
    async def insert_if_not_exists(self, price: PredictionMarketPrice) -> bool:
        """Atomically insert one price bar; ``True`` if new, ``False`` on conflict.

        Conflict target: ``(market_id, token_id, interval, window_start_ts)``.
        """

    @abstractmethod
    async def bulk_insert(self, prices: list[PredictionMarketPrice]) -> int:
        """Insert many price bars in one multi-row ``INSERT … ON CONFLICT DO NOTHING``.

        Used by the historical backfill path (BP-034/035 idempotent inserts).
        Returns the number of rows actually inserted (conflicts are skipped).
        An empty list is a no-op returning ``0``.
        """

    @abstractmethod
    async def list_prices(
        self,
        market_id: str,
        *,
        token_id: str | None,
        interval: str | None,
        from_dt: datetime | None,
        to_dt: datetime | None,
        limit: int,
    ) -> list[PredictionMarketPrice]:
        """Return price bars for ``market_id``, ordered by ``window_start_ts DESC``.

        Optional ``token_id`` / ``interval`` narrow to one series; ``from_dt`` /
        ``to_dt`` bound the window (inclusive).
        """


class PredictionMarketTradesRepository(ABC):
    """Port for individual trade/fill (hypertable) operations (PLAN-0056 A2)."""

    @abstractmethod
    async def insert_if_not_exists(self, trade: PredictionMarketTrade) -> bool:
        """Atomically insert one trade; ``True`` if new, ``False`` on conflict.

        Conflict target: ``(market_id, trade_id, ts)``.
        """

    @abstractmethod
    async def bulk_insert(self, trades: list[PredictionMarketTrade]) -> int:
        """Insert many trades in one multi-row ``INSERT … ON CONFLICT DO NOTHING``.

        Returns the number of rows actually inserted. Empty list → ``0``.
        """

    @abstractmethod
    async def list_trades(
        self,
        market_id: str,
        *,
        since: datetime | None,
        limit: int,
    ) -> list[PredictionMarketTrade]:
        """Return trades for ``market_id``, ordered by ``ts DESC``.

        Optional ``since`` bounds the window to ``ts >= since`` (inclusive).
        """


class PredictionMarketOIRepository(ABC):
    """Port for daily open-interest / 24h-volume roll-up operations (PLAN-0056 A2)."""

    @abstractmethod
    async def upsert(self, oi: PredictionMarketOI) -> None:
        """Insert or overwrite the daily roll-up for ``(market_id, snapshot_date)``.

        On conflict the money fields are overwritten (last-write-wins) so a later
        poll on the same day supersedes an earlier partial reading.
        """

    @abstractmethod
    async def list_oi(
        self,
        market_id: str,
        *,
        from_date: date | None,
        to_date: date | None,
        limit: int,
    ) -> list[PredictionMarketOI]:
        """Return daily roll-ups for ``market_id``, ordered by ``snapshot_date DESC``.

        Optional ``from_date`` / ``to_date`` bound the range (inclusive).
        """

    @abstractmethod
    async def get_latest(self, market_id: str) -> PredictionMarketOI | None:
        """Return the most recent daily roll-up for ``market_id`` (or ``None``)."""


class PredictionMarketEventsRepository(ABC):
    """Port for Polymarket "event" group operations (PLAN-0056 A2)."""

    @abstractmethod
    async def upsert(self, event: PredictionEvent) -> None:
        """Insert or update the event keyed on ``event_id`` (last-write-wins metadata)."""

    @abstractmethod
    async def link_markets(self, event_id: str, market_ids: Sequence[str]) -> int:
        """Set ``prediction_markets.event_id = event_id`` for the given market_ids.

        Backfills the market->event linkage (PLAN-0056 Wave A3 completion). Same
        DB as this repository (market_data_db), so it is a plain intra-DB UPDATE,
        not a cross-service read (R9-safe). Idempotent: only rows whose event_id
        differs are touched (``IS DISTINCT FROM``). Returns the number of rows
        updated. An empty ``market_ids`` is a no-op returning 0.
        """

    @abstractmethod
    async def find_by_event_id(self, event_id: str) -> PredictionEvent | None:
        """Return the event with the given ``event_id`` (or ``None`` if absent)."""

    @abstractmethod
    async def list_events(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[PredictionEvent], int]:
        """Return a page of events (ordered by ``start_date DESC NULLS LAST``) + total count."""
