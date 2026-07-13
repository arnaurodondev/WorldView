"""Domain events for the market-data service.

Domain events are immutable records of something that happened within the
domain.  They are frozen dataclasses: once created their state cannot change.

``event_id`` and ``occurred_at`` are auto-populated at construction time so
callers only need to supply domain-specific fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from common.ids import new_uuid7_str  # type: ignore[import-untyped]
from common.time import to_iso8601, utc_now  # type: ignore[import-untyped]


def _new_event_id() -> str:
    """Generate a UUIDv7 string for use as an event identifier."""
    return new_uuid7_str()


def _utc_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return to_iso8601(utc_now())


@dataclass(frozen=True)
class DomainEvent:
    """Base envelope for all market-data domain events.

    ``event_type`` and ``schema_version`` are class-level constants (ClassVar)
    that subclasses override.  They are not dataclass instance fields so that
    they cannot vary per-instance and are not included in ``dataclasses.asdict()``.
    Serialization code that needs them must read them explicitly via ``type(event)``.
    """

    event_type: ClassVar[str] = ""
    schema_version: ClassVar[int] = 1

    event_id: str = field(default_factory=_new_event_id)
    occurred_at: str = field(default_factory=_utc_iso)
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True)
class InstrumentCreated(DomainEvent):
    """Emitted when a new instrument is first seen during data ingestion.

    Published to topic ``market.instrument.created``.

    schema_version=2: adds optional name, isin, instrument_type fields populated
    from EODHD company_profile data when available.

    schema_version=3 (PLAN-0057 Wave C-1, F-CRIT-04 / F-CRIT-11): adds four
    additional EODHD identifier fields — ``cusip``, ``figi`` (from EODHD
    ``OpenFigi``), ``lei`` and ``primary_ticker`` — so that S7 can insert a rich
    alias suite on the canonical entity (CUSIP / FIGI / LEI / PRIMARY_TICKER).
    All four are nullable with default ``None`` for backward compatibility.
    """

    event_type: ClassVar[str] = "market.instrument.created"
    schema_version: ClassVar[int] = 3

    instrument_id: str = ""
    security_id: str = ""
    symbol: str = ""
    exchange: str = ""
    name: str | None = None
    isin: str | None = None
    instrument_type: str | None = None
    description: str | None = None  # From EODHD General.Description — used by S7 for definition embedding
    # ── PLAN-0057 Wave C-1: EODHD identifier extras (schema_version=3) ────
    # Source: EODHD General.{CUSIP, OpenFigi, LEI, PrimaryTicker}.  Each is
    # nullable because the upstream EODHD response may omit any of them
    # depending on the security and account tier; S7 only inserts the matching
    # alias when the value is present and non-empty.
    cusip: str | None = None
    figi: str | None = None  # mapped from EODHD General.OpenFigi (NOT 'FIGI')
    lei: str | None = None
    primary_ticker: str | None = None


@dataclass(frozen=True)
class InstrumentDiscovered(DomainEvent):
    """Emitted when an instrument is first observed during OHLCV/Quotes ingestion.

    PLAN-0057 Wave D-2: This event replaces ``InstrumentCreated`` in the
    OHLCV/Quotes path because at that stage we only know ``symbol`` and
    ``exchange`` (no real ``name`` from EODHD fundamentals).  Producing
    ``market.instrument.created`` with ``name=None`` previously caused
    placeholder canonicals like ``Instrument-019dbbdb...`` (audit
    finding F-CRIT-12).

    Consumers:
      * Portfolio (S2) — materialises ``InstrumentRef`` immediately so the
        portfolio service can reference the instrument.
      * Knowledge-graph (S7) — creates a *lightweight* canonical entity with
        ``canonical_name = symbol`` and
        ``metadata.needs_fundamentals_enrichment = true``.  The existing
        ``InstrumentEntityConsumer`` upserts the real name and rich aliases
        later when ``market.instrument.created`` arrives from the
        fundamentals consumer.

    ``market.instrument.created`` is now produced ONLY by
    ``fundamentals_consumer`` and is gated on having a real ``Name`` from
    EODHD.

    Published to topic ``market.instrument.discovered.v1``.
    """

    event_type: ClassVar[str] = "market.instrument.discovered"
    schema_version: ClassVar[int] = 1

    instrument_id: str = ""
    symbol: str = ""
    # ``exchange`` is nullable in the Avro schema — provider may not always supply.
    exchange: str | None = None


@dataclass(frozen=True)
class InstrumentUpdated(DomainEvent):
    """Emitted when an existing instrument's capability flags change.

    Published to topic ``market.instrument.updated``.

    ``fields_updated`` lists the names of the fields that changed so consumers
    can selectively process the update without inspecting all flag values.
    """

    event_type: ClassVar[str] = "market.instrument.updated"
    schema_version: ClassVar[int] = 1

    instrument_id: str = ""
    symbol: str = ""
    exchange: str = ""
    has_ohlcv: bool = False
    has_quotes: bool = False
    has_fundamentals: bool = False
    fields_updated: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PredictionMarketMove(DomainEvent):
    """Emitted by the S3 ``PredictionMoveDetector`` when a prediction market's
    implied probability for one outcome moves *materially* over a lookback
    window (PLAN-0056 Wave D1).

    Published to topic ``market.prediction.move.v1`` (Avro schema
    ``market.prediction.move.v1.avsc``).  Consumed by the S7
    ``PredictionSignalEmitter`` (Wave D2) which joins the ``market_id``
    (Polymarket ``conditionId``) to entity exposures + polarity and fans a
    per-entity signal out to the alert pipeline.

    A move is only emitted when it clears three config-driven gates so noise
    never fires: ``|delta| >= τ`` AND ``liquidity >= floor`` AND
    ``volume_24h >= floor`` (all from the latest snapshot).  ``prev_price`` is
    the implied probability at the window start, ``new_price`` at the window
    end; ``delta = new_price - prev_price`` (signed) and ``direction`` is
    ``"up"``/``"down"``.

    Field ordering places every field after the base ``DomainEvent`` defaults;
    all carry defaults so the frozen dataclass respects the "no non-default
    after default" rule.  ``prev_price``/``new_price``/``delta`` are plain
    ``float`` to match the Avro ``double`` fields (no ``Decimal`` round-trip).
    """

    event_type: ClassVar[str] = "market.prediction.move"
    schema_version: ClassVar[int] = 1

    market_id: str = ""  # Polymarket conditionId
    token_id: str = ""  # CLOB token id of the outcome that moved
    interval: str = ""  # window granularity label: 1h | 1d | 1w
    prev_price: float = 0.0  # implied probability at window start [0,1]
    new_price: float = 0.0  # implied probability at window end [0,1]
    delta: float = 0.0  # new_price - prev_price (signed)
    direction: str = ""  # up | down
    window_start_ts: str = ""  # ISO-8601 UTC start of the move window
    outcome_name: str | None = None  # e.g. Yes/No, when known
    liquidity: float | None = None  # USD liquidity at detection (conviction)
    volume_24h: float | None = None  # USD 24h volume at detection (conviction)
    is_backfill: bool = False  # True when computed over backfilled history
