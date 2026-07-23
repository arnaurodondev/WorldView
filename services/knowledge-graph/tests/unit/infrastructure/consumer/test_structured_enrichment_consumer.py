"""Unit tests for StructuredEnrichmentConsumer (PRD-0073 §9.5 hot path).

Covers F-Q02 of the PLAN-0073 QA report.

Behaviour under test:
    * happy path: payload → load entity from DB → invoke use case
    * defensive: missing entity_id payload → log warning, return early
    * defensive: DB returns None for entity → log warning, return early
    * idempotency:
        - is_duplicate() returns False when no dedup_client configured
        - is_duplicate() returns True when key exists in Valkey
        - mark_processed() writes with 24 h TTL
    * deserialization:
        - Confluent-Avro wire format (magic byte 0x00) decodes correctly
        - JSON fallback for legacy payloads
        - JSON fallback above 16 MiB raises MalformedDataError
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000001")


def _row_for_entity() -> tuple:
    """Mirror the SELECT column order in the consumer's process_message()."""
    return (
        str(_ENTITY_ID),
        "Apple Inc.",
        "financial_instrument",
        "AAPL",
        None,  # isin
        "NASDAQ",
        {},  # metadata jsonb
        0,  # enrichment_attempts
        None,  # description
        None,  # data_completeness
        None,  # enriched_at
    )


def _make_session_factory(row: tuple | None) -> tuple[MagicMock, AsyncMock]:
    """Build a session factory that returns a row (or None) for the SELECT.

    Returns ``(factory, session)`` so tests can assert against the session.
    """
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.fetchone = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()

    sf = MagicMock()
    sf.return_value.__aenter__ = AsyncMock(return_value=session)
    sf.return_value.__aexit__ = AsyncMock(return_value=False)
    return sf, session


# Sentinel — lets tests distinguish "row arg omitted" (use default happy-path
# row) from "row=None explicitly passed" (simulate DB-not-found path).
_UNSET: object = object()


def _make_consumer(
    *,
    row: tuple | None | object = _UNSET,
    use_case: AsyncMock | None = None,
    dedup_client: AsyncMock | None = None,
) -> object:
    from knowledge_graph.infrastructure.messaging.consumers.structured_enrichment_consumer import (
        StructuredEnrichmentConsumer,
    )

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-structured-enrichment",
        topics=["entity.canonical.created.v1"],
    )
    effective_row = _row_for_entity() if row is _UNSET else row
    sf, _session = _make_session_factory(effective_row)  # type: ignore[arg-type]
    return StructuredEnrichmentConsumer(
        config=config,
        session_factory=sf,
        use_case=use_case or AsyncMock(),
        dedup_client=dedup_client,
    )


# ---------------------------------------------------------------------------
# process_message
# ---------------------------------------------------------------------------


class TestProcessMessage:
    async def test_loads_entity_and_invokes_use_case(self) -> None:
        """Happy path — DB returns a row → CanonicalEntity built → use_case.enrich called."""
        use_case = AsyncMock()
        use_case.enrich = AsyncMock()
        consumer = _make_consumer(row=_row_for_entity(), use_case=use_case)

        await consumer.process_message(  # type: ignore[union-attr]
            key=str(_ENTITY_ID),
            value={"entity_id": str(_ENTITY_ID), "event_id": "evt-1"},
            headers={},
        )

        use_case.enrich.assert_awaited_once()
        passed_entity = use_case.enrich.call_args.args[0]
        assert passed_entity.entity_id == _ENTITY_ID
        assert passed_entity.canonical_name == "Apple Inc."
        assert passed_entity.entity_type == "financial_instrument"
        assert passed_entity.ticker == "AAPL"

    async def test_skips_when_entity_id_missing(self) -> None:
        """Payload without entity_id → log warning + return early; use_case never called."""
        use_case = AsyncMock()
        use_case.enrich = AsyncMock()
        consumer = _make_consumer(use_case=use_case)

        await consumer.process_message(  # type: ignore[union-attr]
            key="x",
            value={"event_id": "evt-1"},  # entity_id absent
            headers={},
        )

        use_case.enrich.assert_not_called()

    async def test_skips_when_entity_not_found_in_db(self) -> None:
        """SELECT returns None → log + early return, no enrichment."""
        use_case = AsyncMock()
        use_case.enrich = AsyncMock()
        consumer = _make_consumer(row=None, use_case=use_case)

        await consumer.process_message(  # type: ignore[union-attr]
            key=str(_ENTITY_ID),
            value={"entity_id": str(_ENTITY_ID), "event_id": "evt-1"},
            headers={},
        )

        use_case.enrich.assert_not_called()

    @pytest.mark.skip(reason="depends on F-A03 fix — consumer would skip non-financial types upstream of use_case")
    async def test_skips_non_financial_entity_types(self) -> None:
        """Per F-A03 the consumer should short-circuit for person/concept etc.

        Currently the consumer hands every entity_type to the use_case (which
        does its own LLM-only routing). When F-A03 lands and the consumer is
        modified to filter, this test will be unskipped.
        """


# ---------------------------------------------------------------------------
# Idempotency / dedup
# ---------------------------------------------------------------------------


class TestIdempotency:
    async def test_is_duplicate_returns_false_without_dedup_client(self) -> None:
        consumer = _make_consumer(dedup_client=None)
        assert await consumer.is_duplicate("evt-1") is False  # type: ignore[union-attr]

    async def test_is_duplicate_returns_true_when_key_exists(self) -> None:
        dedup = AsyncMock()
        dedup.exists = AsyncMock(return_value=1)  # truthy
        consumer = _make_consumer(dedup_client=dedup)

        assert await consumer.is_duplicate("evt-1") is True  # type: ignore[union-attr]
        # Verify the namespaced key shape: <prefix>:<event_id>
        called_key = dedup.exists.call_args.args[0]
        assert called_key.endswith(":evt-1")
        assert "kg-se-dedup:" in called_key

    async def test_mark_processed_writes_24h_ttl(self) -> None:
        dedup = AsyncMock()
        dedup.set = AsyncMock()
        consumer = _make_consumer(dedup_client=dedup)

        await consumer.mark_processed("evt-1")  # type: ignore[union-attr]

        dedup.set.assert_awaited_once()
        # Verify ex=86400 (24 h) and the marker value.
        _args, kwargs = dedup.set.call_args
        assert kwargs.get("ex") == 86400


# ---------------------------------------------------------------------------
# Deserialization
# ---------------------------------------------------------------------------


class TestDeserialize:
    def test_deserialize_avro_wire_format(self) -> None:
        """Confluent-Avro envelope (magic byte 0x00) decodes round-trip."""
        from knowledge_graph.infrastructure.messaging.consumers.structured_enrichment_consumer import (
            _ENTITY_CANONICAL_CREATED_SCHEMA_PATH,
        )

        from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

        record = {
            "event_id": "01900000-0000-7000-0000-000000000010",
            "event_type": "entity.canonical.created",
            "schema_version": 1,
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "entity_id": str(_ENTITY_ID),
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "provisional_queue_id": "01234567-89ab-7def-8012-000000000099",
            "alias_texts": ["Apple Inc.", "AAPL"],
            "correlation_id": None,
        }
        wire = serialize_confluent_avro(_ENTITY_CANONICAL_CREATED_SCHEMA_PATH, record)

        consumer = _make_consumer()
        decoded = consumer.deserialize_value(wire)  # type: ignore[union-attr]
        assert decoded["entity_id"] == str(_ENTITY_ID)

    def test_deserialize_json_fallback(self) -> None:
        """A payload starting with `{` (no magic byte) is decoded via json.loads."""
        consumer = _make_consumer()
        raw = json.dumps({"entity_id": str(_ENTITY_ID), "event_id": "evt-1"}).encode()
        # NB: bytes in raw start with `{` (0x7b), so the magic-byte check is skipped.
        decoded = consumer.deserialize_value(raw)  # type: ignore[union-attr]
        assert decoded["entity_id"] == str(_ENTITY_ID)

    def test_deserialize_payload_too_large_raises(self) -> None:
        """JSON fallback must reject payloads above the 16 MiB cap before parsing."""
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

        consumer = _make_consumer()
        # First byte != 0x00 forces JSON branch; size > 16 MiB triggers cap.
        oversized = b'{"x":"' + b"a" * (17 * 1024 * 1024) + b'"}'
        with pytest.raises(MalformedDataError):
            consumer.deserialize_value(oversized)  # type: ignore[union-attr]

    @pytest.mark.skip(reason="depends on F-X05 fix — extract_event_id should raise on missing field")
    def test_extract_event_id_raises_on_missing_event_id(self) -> None:
        """When F-X05 lands, missing event_id must surface (not silently empty-string)."""


# ---------------------------------------------------------------------------
# Failure tracking — sanity (the consumer's overrides are mostly logging stubs)
# ---------------------------------------------------------------------------


class TestFailureHooks:
    async def test_get_pending_retries_returns_empty_list(self) -> None:
        consumer = _make_consumer()
        assert await consumer.get_pending_retries() == []  # type: ignore[union-attr]

    async def test_extract_event_id_returns_string(self) -> None:
        """extract_event_id pulls 'event_id' from the payload as a string."""
        consumer = _make_consumer()
        assert consumer.extract_event_id({"event_id": "abc"}) == "abc"  # type: ignore[union-attr]

    async def test_extract_event_id_raises_on_missing(self) -> None:
        """F-X05 fix: missing event_id surfaces as MalformedDataError (not silent empty)."""
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

        consumer = _make_consumer()
        with pytest.raises(MalformedDataError):
            consumer.extract_event_id({})  # type: ignore[union-attr]
        with pytest.raises(MalformedDataError):
            consumer.extract_event_id({"event_id": ""})  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Use-case errors propagate
# ---------------------------------------------------------------------------


class TestUseCaseErrorsPropagate:
    async def test_use_case_exception_re_raised(self) -> None:
        """If the use case raises, the consumer re-raises so BaseKafkaConsumer
        can route the message into its retry/dead-letter path."""
        use_case = AsyncMock()
        use_case.enrich = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        consumer = _make_consumer(use_case=use_case)

        with pytest.raises(RuntimeError, match="LLM unavailable"):
            await consumer.process_message(  # type: ignore[union-attr]
                key=str(_ENTITY_ID),
                value={"entity_id": str(_ENTITY_ID), "event_id": "evt-1"},
                headers={},
            )

    async def test_dedup_check_exception_returns_false(self) -> None:
        """is_duplicate falls back to False when Valkey errors — soft-fail."""
        dedup = AsyncMock()
        dedup.exists = AsyncMock(side_effect=RuntimeError("valkey down"))
        consumer = _make_consumer(dedup_client=dedup)

        assert await consumer.is_duplicate("evt-1") is False  # type: ignore[union-attr]

    async def test_mark_processed_exception_swallowed(self) -> None:
        """mark_processed must not raise if Valkey is unavailable."""
        dedup = AsyncMock()
        dedup.set = AsyncMock(side_effect=RuntimeError("valkey down"))
        consumer = _make_consumer(dedup_client=dedup)

        # No exception expected.
        await consumer.mark_processed("evt-1")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Patched-import sanity guard
# ---------------------------------------------------------------------------


class TestImports:
    def test_module_imports_cleanly(self) -> None:
        """The consumer module must be importable without side effects."""
        with patch.dict("os.environ", {}, clear=False):
            import knowledge_graph.infrastructure.messaging.consumers.structured_enrichment_consumer as mod  # noqa: F401


# ---------------------------------------------------------------------------
# Recurrence-1 structural fix (2026-07-23 bottleneck audit / BP-736)
# ---------------------------------------------------------------------------


class _FakeKafkaMessage:
    """Minimal confluent-Kafka message stand-in for ``_handle_message`` tests."""

    def __init__(self, raw_value: bytes, *, offset: int = 777, partition: int = 0) -> None:
        self._value = raw_value
        self._offset = offset
        self._partition = partition

    def topic(self) -> str:
        return "entity.canonical.created.v1"

    def value(self) -> bytes:
        return self._value

    def key(self) -> bytes | None:
        return None

    def headers(self) -> list[tuple[str, bytes]]:
        return []

    def offset(self) -> int:
        return self._offset

    def partition(self) -> int:
        return self._partition


class TestStructuredEnrichmentConsumerResilientDeserialize:
    """An un-decodable/poison record must be SKIPPED, not crash-loop the group.

    This consumer never had its own ``_handle_message`` override for the
    deserialize-poison case (its override at line 113 only handles
    ``RetryableEnrichmentError`` from ``process_message`` and calls
    ``super()._handle_message(msg)`` first), so before the base-class fix a
    poison Avro record on ``entity.canonical.created.v1`` would wrap into
    ``MalformedDataError`` and dead-letter inline — a burst of them would
    trip ``dead_letter_cap`` and crash-loop the consumer. The skip-and-advance
    behaviour now lives in ``BaseKafkaConsumer._handle_message`` itself
    (``ConsumerConfig.skip_undecodable_records``, default True), so this
    consumer is protected automatically with zero source changes; this test
    guards the regression.
    """

    async def test_undecodable_old_schema_record_is_skipped_not_raised(self) -> None:
        from structlog.testing import capture_logs

        consumer = _make_consumer()
        msg = _FakeKafkaMessage(b"\x00garbage-not-avro")
        with (
            patch.object(consumer, "deserialize_value", side_effect=EOFError("short read")),
            capture_logs() as logs,
        ):
            await consumer._handle_message(msg)  # must not raise
        assert any(e["event"] == "kafka_consumer_deserialize_skipped" for e in logs)
        skip = next(e for e in logs if e["event"] == "kafka_consumer_deserialize_skipped")
        assert skip["offset"] == 777
        assert consumer._dead_letter_count == 0
