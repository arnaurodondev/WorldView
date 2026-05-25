"""Domain entities for the market-data service.

Entities represent the core business objects that have identity (ID) and can
change state over time.  They carry no framework dependencies — no SQLAlchemy
models, no Pydantic schemas.  ORM models are infrastructure concerns (wave 02).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now as _common_utc_now  # type: ignore[import-untyped]
from market_data.domain.enums import FundamentalsSection, PeriodType, Timeframe
from market_data.domain.value_objects import InstrumentFlags, ProviderPriority


def _new_id() -> str:
    """Generate a new UUIDv7 string for entity identity."""
    return str(new_uuid7())


def _utc_now() -> datetime:
    """Return current UTC-aware datetime."""
    return _common_utc_now()


def _default_flags() -> InstrumentFlags:
    return InstrumentFlags()


def _default_provider_priority() -> ProviderPriority:
    return ProviderPriority(provider="unknown", priority=0)


@dataclass
class Security:
    """A listed company or financial security (master record).

    One Security can be traded on multiple exchanges; each trading listing is
    represented by a separate ``Instrument``.
    """

    id: str = field(default_factory=_new_id)
    figi: str | None = None
    isin: str | None = None
    name: str = ""
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    currency: str | None = None
    description: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


@dataclass
class Instrument:
    """A trading instrument — a specific listing of a Security on an exchange.

    Carries ``InstrumentFlags`` to record which dataset types have been
    ingested, which drives cache-warm-up and API availability responses.
    """

    id: str = field(default_factory=_new_id)
    security_id: str = ""
    symbol: str = ""
    exchange: str = ""
    flags: InstrumentFlags = field(default_factory=_default_flags)
    is_active: bool = True
    created_at: datetime = field(default_factory=_utc_now)
    # Enrichment fields populated from the company_profile fundamentals section
    name: str | None = None
    isin: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    currency_code: str | None = None
    # FIX-LIVE-P: month (1-12) of the fiscal-year end. Needed to compute fiscal
    # quarter labels for companies whose fiscal year does not align with the
    # calendar (NVDA=1, AAPL=9, MSFT=6). None when unknown — label code falls
    # back to calendar-year quarters and emits a structured warning.
    fiscal_year_end_month: int | None = None


@dataclass
class OHLCVBar:
    """A single OHLCV candlestick bar for an instrument at a given timeframe.

    Price fields use ``Decimal`` to match the database ``NUMERIC(18,6)``
    column type and avoid float precision loss during DB round-trips.
    ``provider_priority`` is stored so the upsert logic can discard lower-
    priority data without re-querying.

    ``is_derived`` marks bars that were computed locally (e.g. weekly/monthly
    bars aggregated from daily bars) rather than ingested directly from an
    external provider.  Derived bars are never overwritten by live ingestion
    and do not consume EODHD API credits (PLAN-0036 W2-4/W2-5).
    """

    instrument_id: str = ""
    timeframe: Timeframe = Timeframe.ONE_DAY
    bar_date: datetime = field(default_factory=_utc_now)
    open: Decimal = Decimal("0")
    high: Decimal = Decimal("0")
    low: Decimal = Decimal("0")
    close: Decimal = Decimal("0")
    volume: int | None = 0
    adjusted_close: Decimal | None = None
    source: str = ""
    provider_priority: ProviderPriority = field(default_factory=_default_provider_priority)
    ingested_at: datetime = field(default_factory=_utc_now)
    # True for bars derived locally from finer-grained bars (e.g. 1w/1M from 1d).
    # Forward-compatible addition: defaults to False so existing code is unaffected.
    is_derived: bool = False
    # True when this bar represents an incomplete period (e.g. the current week/month
    # whose trading days have not all elapsed).  A partial bar is always derived — it
    # makes no sense for a directly-ingested bar to be partial.
    is_partial: bool = False

    def __post_init__(self) -> None:
        if self.is_partial and not self.is_derived:
            raise ValueError("is_partial=True implies is_derived=True; a directly-ingested bar cannot be partial")


@dataclass
class Quote:
    """Latest bid/ask/last snapshot for an instrument.

    One row per instrument (last-write-wins, not time-series).  The full
    price history is stored in ``OHLCVBar``.

    Price fields use ``Decimal | None`` to preserve data fidelity:
    ``None`` means "no data available", while ``Decimal("0")`` means
    "zero trading activity" (D-004).
    """

    instrument_id: str = ""
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    volume: int | None = None
    timestamp: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class ScreenFieldMetadata:
    """Metadata for a screenable fundamental metric field (PRD-0017 §6.4).

    Static instances represent the 12 supported metric fields.
    Persisted in ``screen_field_metadata`` table; also cached in Valkey.
    """

    name: str
    label: str
    field_type: str  # "numeric" | "text"
    unit: str | None
    description: str | None
    observed_min: float | None
    observed_max: float | None
    null_fraction: float  # 0.0-1.0


@dataclass
class FundamentalsRecord:
    """One section of company fundamentals for a given reporting period.

    The full fundamentals snapshot is decomposed into 13 logical sections
    (see ``FundamentalsSection``).  Each section maps to its own DB table
    (infrastructure concern), but the domain treats them uniformly here.

    ``data`` holds the raw section fields as a key→value mapping; the exact
    schema is determined by the section type and enforced at the
    infrastructure layer.
    """

    id: str = field(default_factory=_new_id)
    security_id: str = ""
    section: FundamentalsSection = FundamentalsSection.INCOME_STATEMENT
    period_end: datetime = field(default_factory=_utc_now)
    period_type: PeriodType = PeriodType.ANNUAL
    data: dict[str, object] = field(default_factory=dict)
    source: str = ""
    ingested_at: datetime = field(default_factory=_utc_now)


@dataclass
class PredictionMarket:
    """A Polymarket prediction market record.

    One row per market (keyed on ``market_id``).  Upserted on every poll
    cycle so that question text, resolution status, and outcomes metadata
    stay current without accumulating history.

    ``outcomes`` holds only static outcome descriptors
    (``[{"name": str, "token_id": str}]``).  Per-poll prices live in
    ``PredictionMarketSnapshot.outcomes_prices``.
    """

    id: str = field(default_factory=_new_id)
    market_id: str = ""
    source: str = "polymarket"
    question: str = ""
    description: str | None = None
    outcomes: list[dict] = field(default_factory=list)
    close_time: datetime | None = None
    resolution_status: str = "open"
    resolved_answer: str | None = None
    # WHY default None: added in migration 009; existing rows populated on next
    # consumer poll. None = "slug not yet known" (distinct from "" which is invalid).
    market_slug: str | None = None
    # PLAN-0049 T-C-3-03 — high-level category tag (``macro`` | ``politics`` |
    # ``sports`` | ``crypto`` | ``general``).  Forward-compatible: defaults to
    # None so existing call-sites and tests are unaffected; the polymarket
    # adapter populates the field once it starts emitting it on the wire.
    category: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class PredictionMarketSnapshot:
    """Per-poll price snapshot for a single Polymarket market.

    Stored in a TimescaleDB hypertable partitioned on ``snapshot_at``.
    Each row is uniquely identified by ``(market_id, snapshot_at)``.

    ``outcomes_prices`` maps outcome name to implied probability (0-1).
    ``volume_24h`` and ``liquidity`` are optional; absent from some markets.
    """

    market_id: str
    snapshot_at: datetime
    outcomes_prices: dict[str, float]
    source_event_id: str
    volume_24h: Decimal | None = None
    liquidity: Decimal | None = None
    id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        if self.snapshot_at.tzinfo is None:
            raise ValueError("snapshot_at must be UTC-aware (naive datetime not allowed)")
        if len(self.outcomes_prices) < 2:
            raise ValueError("outcomes_prices must contain at least 2 outcome entries")
