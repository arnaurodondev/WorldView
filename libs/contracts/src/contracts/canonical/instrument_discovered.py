"""Canonical model for the ``market.instrument.discovered.v1`` event.

PLAN-0057 Wave D-2.  Mirrors the Avro schema at
``infra/kafka/schemas/market.instrument.discovered.v1.avsc`` field-for-field
so that any service can construct or deserialise the event without depending
on ``market-data``'s domain dataclasses.

Consumers (Portfolio S2, Knowledge-Graph S7) receive this dict-shaped payload
from ``deserialize_confluent_avro``; this dataclass is provided as a typed
helper for tests, fixtures, and any service that wants to round-trip through
``CanonicalInstrumentDiscovered.from_dict(...).to_dict()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalInstrumentDiscovered:
    """A lightweight notification that S3 has just observed a new instrument.

    See ``services/market-data/src/market_data/domain/events.py``
    (``InstrumentDiscovered``) for the producer-side dataclass.  The two are
    kept aligned by ``libs/contracts/tests/test_avro_alignment.py``.
    """

    event_id: str
    occurred_at: str
    instrument_id: str
    symbol: str
    exchange: str | None = None
    # Stable cross-service identifier (== instrument_id; M-017 stability pattern).
    # Set by ``event_to_outbox_payload`` on the producer side; consumers (Portfolio
    # S2 in particular) use it as the local primary key so replays are idempotent.
    entity_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    # Constants from the Avro schema (defaults baked in there as well).  We
    # expose them here so consumers can verify ``event_type`` matches without
    # special-casing the dict path.
    event_type: str = field(default="market.instrument.discovered")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalInstrumentDiscovered:
        """Build the canonical model from a deserialised Avro/JSON dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            instrument_id=str(d["instrument_id"]),
            symbol=str(d["symbol"]),
            exchange=str(d["exchange"]) if d.get("exchange") is not None else None,
            entity_id=str(d["entity_id"]) if d.get("entity_id") is not None else None,
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            causation_id=(str(d["causation_id"]) if d.get("causation_id") is not None else None),
            event_type=str(d.get("event_type", "market.instrument.discovered")),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_dict(self) -> dict:
        """Serialise to the Avro-compatible payload shape."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "entity_id": self.entity_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }
