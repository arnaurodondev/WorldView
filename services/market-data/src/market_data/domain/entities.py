"""Domain entities for the market-data service.

Entities represent the core business objects that have identity (ID) and can
change state over time.  They carry no framework dependencies — no SQLAlchemy
models, no Pydantic schemas.  ORM models are infrastructure concerns (wave 02).

ID generation uses ``uuid.uuid4()`` (random UUID).  The ``common.ids`` lib
exposes the same implementation; using stdlib directly keeps this module
dependency-free.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from market_data.domain.enums import FundamentalsSection, PeriodType, Timeframe
from market_data.domain.value_objects import InstrumentFlags, ProviderPriority


def _new_id() -> str:
    """Generate a new random UUID string."""
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    """Return current UTC-aware datetime."""
    return datetime.now(tz=UTC)


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


@dataclass
class OHLCVBar:
    """A single OHLCV candlestick bar for an instrument at a given timeframe.

    Price fields use ``Decimal`` to match the database ``NUMERIC(18,6)``
    column type and avoid float precision loss during DB round-trips.
    ``provider_priority`` is stored so the upsert logic can discard lower-
    priority data without re-querying.
    """

    instrument_id: str = ""
    timeframe: Timeframe = Timeframe.ONE_DAY
    bar_date: datetime = field(default_factory=_utc_now)
    open: Decimal = Decimal("0")
    high: Decimal = Decimal("0")
    low: Decimal = Decimal("0")
    close: Decimal = Decimal("0")
    volume: int = 0
    adjusted_close: Decimal | None = None
    source: str = ""
    provider_priority: ProviderPriority = field(default_factory=_default_provider_priority)
    ingested_at: datetime = field(default_factory=_utc_now)


@dataclass
class Quote:
    """Latest bid/ask/last snapshot for an instrument.

    One row per instrument (last-write-wins, not time-series).  The full
    price history is stored in ``OHLCVBar``.
    """

    instrument_id: str = ""
    bid: Decimal = Decimal("0")
    ask: Decimal = Decimal("0")
    last: Decimal = Decimal("0")
    volume: int = 0
    timestamp: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


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
