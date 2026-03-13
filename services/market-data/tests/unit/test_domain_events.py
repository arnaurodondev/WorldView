"""Unit tests for market_data domain events."""

from __future__ import annotations

import dataclasses

import pytest
from market_data.domain.events import DomainEvent, InstrumentCreated, InstrumentUpdated

pytestmark = pytest.mark.unit


class TestDomainEventAutoFields:
    def test_domain_event_auto_fields(self) -> None:
        event = InstrumentCreated(symbol="AAPL", exchange="NASDAQ")
        # event_id is auto-generated
        assert event.event_id
        assert len(event.event_id) == 36  # UUID format: 8-4-4-4-12
        assert event.event_id.count("-") == 4
        # occurred_at is ISO-8601
        assert event.occurred_at
        assert "T" in event.occurred_at

    def test_two_events_have_different_ids(self) -> None:
        e1 = InstrumentCreated(symbol="AAPL", exchange="NASDAQ")
        e2 = InstrumentCreated(symbol="AAPL", exchange="NASDAQ")
        assert e1.event_id != e2.event_id

    def test_correlation_id_defaults_none(self) -> None:
        event = InstrumentCreated()
        assert event.correlation_id is None
        assert event.causation_id is None

    def test_correlation_id_can_be_set(self) -> None:
        event = InstrumentCreated(correlation_id="corr-1", causation_id="cause-1")
        assert event.correlation_id == "corr-1"
        assert event.causation_id == "cause-1"


class TestInstrumentCreatedEvent:
    def test_instrument_created_event_envelope(self) -> None:
        event = InstrumentCreated(
            instrument_id="inst-1",
            security_id="sec-1",
            symbol="AAPL",
            exchange="NASDAQ",
        )
        assert event.event_type == "market.instrument.created"
        assert event.schema_version == 1
        assert event.instrument_id == "inst-1"
        assert event.security_id == "sec-1"
        assert event.symbol == "AAPL"
        assert event.exchange == "NASDAQ"

    def test_instrument_created_is_frozen(self) -> None:
        event = InstrumentCreated(symbol="AAPL", exchange="NASDAQ")
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.symbol = "MSFT"  # type: ignore[misc]

    def test_instrument_created_inherits_domain_event(self) -> None:
        event = InstrumentCreated()
        assert isinstance(event, DomainEvent)

    def test_instrument_created_event_type_literal(self) -> None:
        assert InstrumentCreated.event_type == "market.instrument.created"  # type: ignore[attr-defined]

    def test_instrument_created_schema_version(self) -> None:
        assert InstrumentCreated.schema_version == 1  # type: ignore[attr-defined]


class TestInstrumentUpdatedEvent:
    def test_instrument_updated_event_envelope(self) -> None:
        event = InstrumentUpdated(
            instrument_id="inst-1",
            symbol="AAPL",
            exchange="NASDAQ",
            has_ohlcv=True,
            has_quotes=True,
            has_fundamentals=False,
        )
        assert event.event_type == "market.instrument.updated"
        assert event.schema_version == 1
        assert event.instrument_id == "inst-1"
        assert event.has_ohlcv is True
        assert event.has_quotes is True
        assert event.has_fundamentals is False

    def test_instrument_updated_default_flags(self) -> None:
        event = InstrumentUpdated(instrument_id="inst-1")
        assert event.has_ohlcv is False
        assert event.has_quotes is False
        assert event.has_fundamentals is False

    def test_instrument_updated_is_frozen(self) -> None:
        event = InstrumentUpdated(instrument_id="inst-1")
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.has_ohlcv = True  # type: ignore[misc]

    def test_instrument_updated_inherits_domain_event(self) -> None:
        event = InstrumentUpdated()
        assert isinstance(event, DomainEvent)
