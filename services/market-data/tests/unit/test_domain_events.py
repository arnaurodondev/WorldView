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
        # PLAN-0057 Wave C-1: schema bumped to 3 (added cusip/figi/lei/primary_ticker)
        assert event.schema_version == 3
        assert event.instrument_id == "inst-1"
        assert event.security_id == "sec-1"
        assert event.symbol == "AAPL"
        assert event.exchange == "NASDAQ"

    def test_instrument_created_optional_fields_default_none(self) -> None:
        """name, isin, instrument_type, description, cusip, figi, lei, primary_ticker default to None."""
        event = InstrumentCreated(instrument_id="inst-1", symbol="AAPL", exchange="NASDAQ")
        assert event.name is None
        assert event.isin is None
        assert event.instrument_type is None
        assert event.description is None
        # PLAN-0057 Wave C-1 fields default to None for backward compatibility.
        assert event.cusip is None
        assert event.figi is None
        assert event.lei is None
        assert event.primary_ticker is None

    def test_instrument_created_has_description_field(self) -> None:
        """description field is present in InstrumentCreated and defaults to None (T-E-2-01)."""
        event = InstrumentCreated(instrument_id="inst-1", symbol="AAPL", exchange="NASDAQ")
        assert hasattr(event, "description")
        assert event.description is None

    def test_instrument_created_description_can_be_set(self) -> None:
        """description can be populated when company profile data is available."""
        event = InstrumentCreated(
            instrument_id="inst-1",
            symbol="AAPL",
            exchange="NASDAQ",
            description="Apple Inc. designs and manufactures consumer electronics.",
        )
        assert event.description == "Apple Inc. designs and manufactures consumer electronics."

    def test_instrument_created_description_in_avro_dict(self) -> None:
        """description is included in the serialized payload via dataclasses.asdict (T-E-2-01)."""
        import dataclasses

        event = InstrumentCreated(
            instrument_id="inst-1",
            symbol="AAPL",
            exchange="NASDAQ",
            description="A technology company.",
        )
        raw = dataclasses.asdict(event)
        assert "description" in raw
        assert raw["description"] == "A technology company."

    def test_instrument_created_description_none_serializes_as_none(self) -> None:
        """description=None serializes as None (not absent) for Avro null union."""
        import dataclasses

        event = InstrumentCreated(instrument_id="inst-1", symbol="AAPL", exchange="NASDAQ")
        raw = dataclasses.asdict(event)
        assert "description" in raw
        assert raw["description"] is None

    def test_instrument_created_optional_fields_can_be_set(self) -> None:
        """name, isin, instrument_type can be set when data is available."""
        event = InstrumentCreated(
            instrument_id="inst-1",
            symbol="AAPL",
            exchange="NASDAQ",
            name="Apple Inc.",
            isin="US0378331005",
            instrument_type="Common Stock",
        )
        assert event.name == "Apple Inc."
        assert event.isin == "US0378331005"
        assert event.instrument_type == "Common Stock"

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
        # PLAN-0057 Wave C-1: schema_version=3 — added cusip, figi, lei, primary_ticker.
        # (Previous v2 added name, isin, instrument_type, description in Wave 5 QA-016.)
        assert InstrumentCreated.schema_version == 3  # type: ignore[attr-defined]

    def test_instrument_created_v3_extra_identifiers_can_be_set(self) -> None:
        """PLAN-0057 Wave C-1: cusip, figi, lei, primary_ticker can be populated."""
        event = InstrumentCreated(
            instrument_id="inst-1",
            symbol="AAPL",
            exchange="NASDAQ",
            cusip="037833100",
            figi="BBG000B9XRY4",
            lei="HWUPKR0MPOU8FGXBT394",
            primary_ticker="AAPL.US",
        )
        assert event.cusip == "037833100"
        assert event.figi == "BBG000B9XRY4"
        assert event.lei == "HWUPKR0MPOU8FGXBT394"
        assert event.primary_ticker == "AAPL.US"

    def test_instrument_created_v3_fields_in_avro_dict(self) -> None:
        """PLAN-0057 Wave C-1: new fields surface via dataclasses.asdict() for Avro encoding."""
        import dataclasses

        event = InstrumentCreated(
            instrument_id="inst-1",
            symbol="AAPL",
            exchange="NASDAQ",
            cusip="037833100",
            figi="BBG000B9XRY4",
            lei="HWUPKR0MPOU8FGXBT394",
            primary_ticker="AAPL.US",
        )
        raw = dataclasses.asdict(event)
        assert raw["cusip"] == "037833100"
        assert raw["figi"] == "BBG000B9XRY4"
        assert raw["lei"] == "HWUPKR0MPOU8FGXBT394"
        assert raw["primary_ticker"] == "AAPL.US"


# ── T-E2-2-02: ClassVar fields not in dataclass fields ────────────────────────


class TestClassVarFields:
    """Verify event_type and schema_version are ClassVar — not dataclass instance fields.

    dataclasses.fields() only returns true instance fields; ClassVar fields are
    excluded.  __dataclass_fields__ includes ClassVar entries but marks them as
    _FIELD_CLASSVAR, so we use dataclasses.fields() for the canonical check.
    """

    def test_event_type_not_an_instance_field(self) -> None:
        """event_type must NOT appear in dataclasses.fields() — it is a ClassVar."""
        field_names = {f.name for f in dataclasses.fields(InstrumentCreated)}
        assert "event_type" not in field_names

    def test_schema_version_not_an_instance_field(self) -> None:
        """schema_version must NOT appear in dataclasses.fields() — it is a ClassVar."""
        field_names = {f.name for f in dataclasses.fields(InstrumentCreated)}
        assert "schema_version" not in field_names

    def test_event_type_accessible_on_class(self) -> None:
        """event_type is accessible as a class attribute (ClassVar access pattern)."""
        assert InstrumentCreated.event_type == "market.instrument.created"  # type: ignore[attr-defined]

    def test_event_type_accessible_on_instance(self) -> None:
        """event_type is accessible on an instance (inherited from class)."""
        event = InstrumentCreated()
        assert event.event_type == "market.instrument.created"


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

    def test_instrument_updated_fields_updated_defaults_empty(self) -> None:
        """fields_updated defaults to an empty tuple."""
        event = InstrumentUpdated(instrument_id="inst-1")
        assert event.fields_updated == ()

    def test_instrument_updated_fields_updated_can_be_set(self) -> None:
        """fields_updated captures which flags changed."""
        event = InstrumentUpdated(
            instrument_id="inst-1",
            symbol="AAPL",
            exchange="NASDAQ",
            has_ohlcv=True,
            fields_updated=("has_ohlcv",),
        )
        assert event.fields_updated == ("has_ohlcv",)


# ── QA-016 regression guard ───────────────────────────────────────────────────


class TestQA016TopicAlignment:
    """Regression guard: event_type values must match dedicated Kafka topic names."""

    def test_instrument_created_event_type_is_not_legacy_topic(self) -> None:
        """QA-016: InstrumentCreated must NOT use the legacy market.events.v1 topic."""
        assert InstrumentCreated.event_type != "market.events.v1"  # type: ignore[attr-defined]
        assert InstrumentCreated.event_type == "market.instrument.created"  # type: ignore[attr-defined]

    def test_instrument_updated_event_type_is_not_legacy_topic(self) -> None:
        """QA-016: InstrumentUpdated must NOT use the legacy market.events.v1 topic."""
        assert InstrumentUpdated.event_type != "market.events.v1"  # type: ignore[attr-defined]
        assert InstrumentUpdated.event_type == "market.instrument.updated"  # type: ignore[attr-defined]
