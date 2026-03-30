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
    """

    event_type: ClassVar[str] = "market.instrument.created"
    schema_version: ClassVar[int] = 2

    instrument_id: str = ""
    security_id: str = ""
    symbol: str = ""
    exchange: str = ""
    name: str | None = None
    isin: str | None = None
    instrument_type: str | None = None
    description: str | None = None  # From EODHD General.Description — used by S7 for definition embedding


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
