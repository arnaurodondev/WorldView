"""Domain events for the market-data service.

Domain events are immutable records of something that happened within the
domain.  They are frozen dataclasses: once created their state cannot change.

``event_id`` and ``occurred_at`` are auto-populated at construction time so
callers only need to supply domain-specific fields.

No shared-library imports — this module is framework-free stdlib-only so that
the domain layer can be tested and reasoned about without any infra dependencies.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


def _new_event_id() -> str:
    """Generate a random UUID string for use as an event identifier."""
    return str(uuid.uuid4())


def _utc_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=UTC).isoformat()


@dataclass(frozen=True)
class DomainEvent:
    """Base envelope for all market-data domain events.

    Subclasses must provide ``event_type`` and ``schema_version`` defaults
    and may add domain-specific payload fields.  All fields in subclasses
    must also carry defaults so that the dataclass inheritance ordering rules
    are satisfied.
    """

    event_id: str = field(default_factory=_new_event_id)
    event_type: str = ""
    schema_version: int = 0
    occurred_at: str = field(default_factory=_utc_iso)
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True)
class InstrumentCreated(DomainEvent):
    """Emitted when a new instrument is first seen during data ingestion.

    Published to topic ``market.instrument.created``.
    """

    instrument_id: str = ""
    security_id: str = ""
    symbol: str = ""
    exchange: str = ""
    # Override envelope defaults
    event_type: str = "market.instrument.created"
    schema_version: int = 1


@dataclass(frozen=True)
class InstrumentUpdated(DomainEvent):
    """Emitted when an existing instrument's capability flags change.

    Published to topic ``market.instrument.updated``.
    """

    instrument_id: str = ""
    symbol: str = ""
    exchange: str = ""
    has_ohlcv: bool = False
    has_quotes: bool = False
    has_fundamentals: bool = False
    # Override envelope defaults
    event_type: str = "market.instrument.updated"
    schema_version: int = 1
