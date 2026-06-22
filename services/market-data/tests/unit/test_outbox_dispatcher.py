"""Unit tests for MarketDataOutboxDispatcher.

Tests run without a live Kafka or schema registry — all external deps are mocked.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from market_data.domain.events import InstrumentCreated, InstrumentUpdated
from market_data.infrastructure.messaging.outbox.dispatcher import (
    EVENT_TOPIC_MAP,
    _event_to_avro_dict,
    _sanitize_payload,
    event_to_outbox_payload,
)

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_dispatcher():
    """Return a MarketDataOutboxDispatcher with all infra deps mocked."""
    from market_data.infrastructure.messaging.outbox.dispatcher import (
        MarketDataOutboxDispatcher,
    )

    settings = MagicMock()
    settings.schema_registry_url = "http://mock-registry:8081"
    settings.kafka_bootstrap_servers = "mock:9092"
    session_factory = MagicMock()

    from messaging.kafka.dispatcher.base import DispatcherConfig

    dispatcher = MarketDataOutboxDispatcher.__new__(MarketDataOutboxDispatcher)
    dispatcher._settings = settings
    dispatcher._session_factory = session_factory
    dispatcher._producer = MagicMock()
    dispatcher._serializers = {
        "market.instrument.created": MagicMock(),
        "market.instrument.updated": MagicMock(),
    }
    # Base ``_dispatch_record`` reads ``_config`` and ``_metrics``; provide them so
    # tests that exercise the base recovery path (GAP-A) work with ``__new__``.
    dispatcher._config = DispatcherConfig(delivery_timeout_seconds=0.1)
    dispatcher._metrics = MagicMock()
    return dispatcher


# ── QA-016 regression guard ───────────────────────────────────────────────────


class TestBrokenProducerRecovery:
    """GAP-A: a wedged producer (delivery TimeoutError) must be discarded.

    market-data overrides only ``_dispatch_batch`` (for reclaim warnings) and
    delegates each record to the *base* ``_dispatch_record``, which already
    carries the producer-recovery path. These tests prove that path is live for
    this service (not bypassed) and that the failure is logged with a non-empty
    ``error_type``/``error_repr`` (``str(TimeoutError())`` is empty).
    """

    def _make_record(self) -> MagicMock:
        record = MagicMock()
        record.id = "01HX00000000000000000000MD"
        record.event_type = "market.instrument.created"
        record.topic = "market.instrument.created"
        record.payload = {"instrument_id": "inst-1"}
        record.attempts = 0
        record.partition_key = None
        return record

    def _make_uow(self) -> MagicMock:
        uow = MagicMock()
        uow.outbox = AsyncMock()
        return uow

    async def test_timeout_error_resets_producer_and_logs_type(self) -> None:
        dispatcher = _make_dispatcher()
        # flush() raises TimeoutError → signature of a wedged producer.
        dispatcher._producer.produce = MagicMock()
        dispatcher._producer.flush = MagicMock(side_effect=TimeoutError())

        record = self._make_record()
        uow = self._make_uow()

        with (
            patch.object(dispatcher, "_reset_producer", wraps=dispatcher._reset_producer) as mock_reset,
            patch("messaging.kafka.dispatcher.base.logger") as mock_logger,
        ):
            result = await dispatcher._dispatch_record(record, uow)

        assert result.success is False
        mock_reset.assert_called_once()
        uow.outbox.increment_attempts.assert_awaited_once()
        warn_calls = [
            c for c in mock_logger.warning.call_args_list if c.args and c.args[0] == "outbox_record_dispatch_failed"
        ]
        assert warn_calls, "expected an outbox_record_dispatch_failed warning"
        assert warn_calls[0].kwargs["error_type"] == "TimeoutError"

    async def test_non_timeout_error_does_not_reset_producer(self) -> None:
        dispatcher = _make_dispatcher()
        dispatcher._producer.produce = MagicMock(side_effect=ValueError("bad"))
        dispatcher._producer.flush = MagicMock()

        record = self._make_record()
        uow = self._make_uow()

        with patch.object(dispatcher, "_reset_producer") as mock_reset:
            result = await dispatcher._dispatch_record(record, uow)

        assert result.success is False
        mock_reset.assert_not_called()


class TestDispatcherTopicRouting:
    """QA-016: Each event type must route to its own dedicated topic.

    Before the fix, both events were incorrectly routed to ``market.events.v1``,
    causing portfolio (S1) to never receive instrument sync events.
    """

    def test_instrument_created_routes_to_own_topic(self) -> None:
        """InstrumentCreated must route to market.instrument.created (not market.events.v1)."""
        assert EVENT_TOPIC_MAP["market.instrument.created"] == "market.instrument.created"

    def test_instrument_updated_routes_to_own_topic(self) -> None:
        """InstrumentUpdated must route to market.instrument.updated (not market.events.v1)."""
        assert EVENT_TOPIC_MAP["market.instrument.updated"] == "market.instrument.updated"

    def test_no_event_routes_to_market_events_v1(self) -> None:
        """QA-016 guard: no event type may route to the legacy market.events.v1 topic."""
        for event_type, topic in EVENT_TOPIC_MAP.items():
            assert topic != "market.events.v1", (
                f"Event type '{event_type}' still routes to legacy topic 'market.events.v1' "
                f"— this causes silent message loss in portfolio (S1). Fix: use dedicated topic."
            )

    def test_all_domain_event_types_have_routes(self) -> None:
        """Every domain event type must have a topic mapping."""
        for event_type in ("market.instrument.created", "market.instrument.updated"):
            assert event_type in EVENT_TOPIC_MAP, f"Missing route for {event_type}"

    def test_each_event_type_routes_to_matching_topic(self) -> None:
        """Each event type must route to a topic whose name is either:
        * exactly equal (self-referential routing — the historical default), OR
        * the event_type plus a ``.v1`` version suffix (introduced in
          PLAN-0057 Wave D-2 for ``market.instrument.discovered`` →
          ``market.instrument.discovered.v1``).
        """
        for event_type, topic in EVENT_TOPIC_MAP.items():
            assert topic in (
                event_type,
                f"{event_type}.v1",
            ), f"event_type '{event_type}' routes to topic '{topic}' — expected '{event_type}' or '{event_type}.v1'"

    def test_instrument_created_event_type_field(self) -> None:
        """InstrumentCreated.event_type must match the routing key."""
        event = InstrumentCreated(instrument_id="x", security_id="y", symbol="AAPL", exchange="NASDAQ")
        assert event.event_type == "market.instrument.created"
        assert event.event_type in EVENT_TOPIC_MAP

    def test_instrument_updated_event_type_field(self) -> None:
        """InstrumentUpdated.event_type must match the routing key."""
        event = InstrumentUpdated(
            instrument_id="x",
            symbol="AAPL",
            exchange="NASDAQ",
            has_ohlcv=True,
            has_quotes=False,
            has_fundamentals=False,
        )
        assert event.event_type == "market.instrument.updated"
        assert event.event_type in EVENT_TOPIC_MAP


class TestAvroSerialization:
    """Assert output dict matches expected Avro schema shape."""

    def test_dispatcher_serializes_instrument_created_avro(self) -> None:
        """_event_to_avro_dict must produce all required fields for InstrumentCreated."""
        event = InstrumentCreated(
            instrument_id="inst-001",
            security_id="sec-001",
            symbol="AAPL",
            exchange="NASDAQ",
        )
        avro_dict = _event_to_avro_dict(event)

        assert "event_id" in avro_dict
        assert "event_type" in avro_dict
        assert avro_dict["event_type"] == "market.instrument.created"
        assert avro_dict["instrument_id"] == "inst-001"
        assert avro_dict["security_id"] == "sec-001"
        assert avro_dict["symbol"] == "AAPL"
        assert avro_dict["exchange"] == "NASDAQ"
        assert "occurred_at" in avro_dict
        assert "schema_version" in avro_dict

    def test_dispatcher_serializes_instrument_updated_avro(self) -> None:
        """_event_to_avro_dict must produce all required fields for InstrumentUpdated."""
        event = InstrumentUpdated(
            instrument_id="inst-002",
            symbol="MSFT",
            exchange="NASDAQ",
            has_ohlcv=True,
            has_quotes=True,
            has_fundamentals=False,
        )
        avro_dict = _event_to_avro_dict(event)

        assert avro_dict["event_type"] == "market.instrument.updated"
        assert avro_dict["instrument_id"] == "inst-002"
        assert avro_dict["has_ohlcv"] is True
        assert avro_dict["has_quotes"] is True
        assert avro_dict["has_fundamentals"] is False

    def test_avro_dict_contains_no_non_primitive_types(self) -> None:
        """The Avro dict must only contain types Confluent AvroSerializer accepts."""
        event = InstrumentCreated(
            instrument_id="inst-003",
            security_id="sec-003",
            symbol="SPY",
            exchange="NYSE",
        )
        avro_dict = _event_to_avro_dict(event)

        for key, value in avro_dict.items():
            assert not isinstance(value, Decimal), f"Field {key} is still a Decimal"
            assert not isinstance(value, UUID), f"Field {key} is still a UUID"


class TestEventToOutboxPayload:
    """Assert event_to_outbox_payload() produces the correct outbox dict."""

    def test_outbox_payload_sets_entity_id_from_instrument_id(self) -> None:
        """event_to_outbox_payload must set entity_id = instrument_id (M-017)."""
        event = InstrumentCreated(instrument_id="inst-abc", symbol="AAPL", exchange="NASDAQ")
        payload = event_to_outbox_payload(event)

        assert payload["entity_id"] == "inst-abc"
        assert payload["instrument_id"] == "inst-abc"

    def test_outbox_payload_converts_tuple_to_list(self) -> None:
        """fields_updated tuple must be converted to list for Avro array compatibility."""
        event = InstrumentUpdated(
            instrument_id="inst-xyz",
            symbol="MSFT",
            exchange="NASDAQ",
            has_ohlcv=True,
            fields_updated=("has_ohlcv",),
        )
        payload = event_to_outbox_payload(event)

        assert isinstance(payload["fields_updated"], list)
        assert payload["fields_updated"] == ["has_ohlcv"]

    def test_outbox_payload_includes_classvars(self) -> None:
        """event_to_outbox_payload must include event_type and schema_version.

        PLAN-0057 Wave C-1: schema_version=3 (was 2) — added cusip, figi, lei,
        primary_ticker EODHD identifier fields.
        """
        event = InstrumentCreated(instrument_id="x", symbol="AAPL", exchange="NASDAQ")
        payload = event_to_outbox_payload(event)

        assert payload["event_type"] == "market.instrument.created"
        assert payload["schema_version"] == 3

    def test_outbox_payload_updated_schema_version(self) -> None:
        """InstrumentUpdated schema_version must be 1."""
        event = InstrumentUpdated(instrument_id="x", symbol="AAPL", exchange="NASDAQ")
        payload = event_to_outbox_payload(event)

        assert payload["schema_version"] == 1


class TestDecimalUUIDSerialization:
    """Assert Decimal → str and UUID → str coercion in _sanitize_payload."""

    def test_decimal_is_cast_to_str(self) -> None:
        """_sanitize_payload must convert Decimal values to str."""
        payload = {"price": Decimal("123.456789"), "name": "test"}
        result = _sanitize_payload(payload)
        assert result["price"] == "123.456789"
        assert isinstance(result["price"], str)

    def test_uuid_is_cast_to_str(self) -> None:
        """_sanitize_payload must convert uuid.UUID values to str."""
        uid = UUID("12345678-1234-5678-1234-567812345678")
        payload = {"id": uid, "label": "foo"}
        result = _sanitize_payload(payload)
        assert result["id"] == "12345678-1234-5678-1234-567812345678"
        assert isinstance(result["id"], str)

    def test_nested_decimal_and_uuid_are_sanitized(self) -> None:
        """_sanitize_payload must recurse into nested dicts."""
        uid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        payload = {
            "outer": "ok",
            "nested": {"price": Decimal("0.01"), "id": uid},
        }
        result = _sanitize_payload(payload)
        assert result["nested"]["price"] == "0.01"
        assert result["nested"]["id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    def test_primitive_values_pass_through_unchanged(self) -> None:
        """_sanitize_payload must not modify str, int, bool, float, or None."""
        payload = {"s": "hello", "i": 42, "b": True, "f": 3.14, "n": None}
        result = _sanitize_payload(payload)
        assert result == payload

    def test_get_serializer_returns_correct_serializer(self) -> None:
        """get_serializer must return the Avro serializer for the given event type."""
        dispatcher = _make_dispatcher()
        ser = dispatcher.get_serializer("market.instrument.created")
        assert ser is not None

    def test_get_serializer_returns_none_for_unknown_event(self) -> None:
        """get_serializer must return None for unknown event types (safe default)."""
        dispatcher = _make_dispatcher()
        ser = dispatcher.get_serializer("unknown.event.type")
        assert ser is None
