"""Unit tests for EntityCreatedConsumer Avro deserialization (PLAN-0062 Wave A).

Tests:
  - test_decodes_confluent_avro_payload — round-trip through serialize_confluent_avro
  - test_falls_back_to_json_for_legacy_payload — pre-PLAN-0062 JSON payload still accepted
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


def _make_consumer() -> object:
    from knowledge_graph.infrastructure.messaging.consumers.entity_consumer import (
        EntityCreatedConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-entity-created-group",
        topics=["entity.canonical.created.v1"],
    )
    return EntityCreatedConsumer(config=config, session_factory=MagicMock())


class TestAvroDeserialization:
    def test_decodes_confluent_avro_payload(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.entity_consumer import (
            _ENTITY_CANONICAL_CREATED_SCHEMA_PATH,
        )

        from messaging.kafka.serialization_utils import serialize_confluent_avro

        consumer = _make_consumer()
        record = {
            "event_id": "01900000-0000-7000-0000-000000000010",
            "event_type": "entity.canonical.created",
            "schema_version": 1,
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "entity_id": "01234567-89ab-7def-8012-345678901234",
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "provisional_queue_id": "01234567-89ab-7def-8012-000000000099",
            "alias_texts": ["Apple Inc.", "AAPL"],
            "correlation_id": None,
        }

        wire_bytes = serialize_confluent_avro(_ENTITY_CANONICAL_CREATED_SCHEMA_PATH, record)
        decoded = consumer.deserialize_value(wire_bytes)  # type: ignore[union-attr]

        assert decoded["entity_id"] == record["entity_id"]
        assert decoded["canonical_name"] == "Apple Inc."
        assert decoded["entity_type"] == "financial_instrument"
        assert list(decoded["alias_texts"]) == ["Apple Inc.", "AAPL"]

    def test_falls_back_to_json_for_legacy_payload(self) -> None:
        import json

        from structlog.testing import capture_logs

        consumer = _make_consumer()
        legacy = json.dumps(
            {
                "event_id": "x",
                "entity_id": "01234567-89ab-7def-8012-345678901234",
                "provisional_queue_id": "01234567-89ab-7def-8012-000000000099",
            },
        ).encode()

        # PLAN-0062 F-021: every JSON-fallback hit must emit a structured warning
        # so we can quantify residual JSON traffic and remove the branch when
        # it decays to zero.
        with capture_logs() as logs:
            decoded = consumer.deserialize_value(legacy)  # type: ignore[union-attr]
        assert decoded["entity_id"] == "01234567-89ab-7def-8012-345678901234"
        warnings = [le for le in logs if le.get("event") == "entity_consumer_legacy_json_payload"]
        assert warnings, "expected entity_consumer_legacy_json_payload warning"

    # ── PLAN-0062 F-018: JSON-fallback oversized payload ─────────────────

    def test_json_fallback_oversized_payload_raises_malformed_data_error(self) -> None:
        """A JSON-fallback payload above the 16 MiB cap must raise
        :class:`MalformedDataError` BEFORE ``json.loads`` is called.
        """
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

        consumer = _make_consumer()
        payload = b'{"x":"' + b"a" * (17 * 1024 * 1024) + b'"}'
        with pytest.raises(MalformedDataError):
            consumer.deserialize_value(payload)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# 2026-06-11 — edge materialization on provisional unblock
# ---------------------------------------------------------------------------


def _make_unblock_session(rows: list[tuple[object, ...]]) -> AsyncMock:
    """Session whose UPDATE ... RETURNING yields *rows*."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


class TestUnblockEdgeMaterialization:
    """When an entity lands, deferred provisional evidence rows whose BOTH
    entities now exist must materialize a graph edge (relation_repo.upsert).
    Rows with a still-missing entity stay deferred and never crash."""

    def test_unblock_with_both_present_materializes_edge(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers import entity_consumer

        landed = uuid4()
        other = uuid4()
        # One unblocked row: (subject, object, canonical_type, extraction_confidence)
        session = _make_unblock_session([(str(landed), str(other), "employs", 0.8)])

        relation_repo = AsyncMock()
        relation_repo.upsert = AsyncMock(return_value=uuid4())
        entity_repo = AsyncMock()
        entity_repo.exists = AsyncMock(return_value=True)

        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository",
                return_value=relation_repo,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository",
                return_value=entity_repo,
            ),
        ):
            rows_updated, edges = asyncio.run(
                entity_consumer._unblock_provisional_evidence(
                    session=session,
                    entity_id=landed,
                    provisional_queue_id=None,
                )
            )
        assert rows_updated == 1
        assert edges == 1
        relation_repo.upsert.assert_called_once()
        kwargs = relation_repo.upsert.call_args.kwargs
        assert kwargs["subject_entity_id"] == landed
        assert kwargs["object_entity_id"] == other
        assert kwargs["canonical_type"] == "employs"

    def test_unblock_with_other_still_missing_defers_no_crash(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers import entity_consumer

        landed = uuid4()
        missing = uuid4()
        session = _make_unblock_session([(str(landed), str(missing), "employs", 0.8)])

        relation_repo = AsyncMock()
        relation_repo.upsert = AsyncMock(return_value=uuid4())
        entity_repo = AsyncMock()
        # The landed entity is cached True; the other entity is missing.
        entity_repo.exists = AsyncMock(side_effect=lambda eid: eid == landed)

        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository",
                return_value=relation_repo,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository",
                return_value=entity_repo,
            ),
        ):
            rows_updated, edges = asyncio.run(
                entity_consumer._unblock_provisional_evidence(
                    session=session,
                    entity_id=landed,
                    provisional_queue_id=None,
                )
            )
        assert rows_updated == 1
        assert edges == 0
        relation_repo.upsert.assert_not_called()

    def test_unblock_skips_unknown_type_rows(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers import entity_consumer

        landed = uuid4()
        other = uuid4()
        # canonical_type is NULL — cannot become an edge (NOT NULL column).
        session = _make_unblock_session([(str(landed), str(other), None, 0.8)])

        relation_repo = AsyncMock()
        relation_repo.upsert = AsyncMock(return_value=uuid4())
        entity_repo = AsyncMock()
        entity_repo.exists = AsyncMock(return_value=True)

        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository",
                return_value=relation_repo,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository",
                return_value=entity_repo,
            ),
        ):
            rows_updated, edges = asyncio.run(
                entity_consumer._unblock_provisional_evidence(
                    session=session,
                    entity_id=landed,
                    provisional_queue_id=None,
                )
            )
        assert rows_updated == 1
        assert edges == 0
        relation_repo.upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Recurrence-1 structural fix (2026-07-23 bottleneck audit / BP-736)
# ---------------------------------------------------------------------------


class _FakeKafkaMessage:
    """Minimal confluent-Kafka message stand-in for ``_handle_message`` tests."""

    def __init__(self, raw_value: bytes, *, offset: int = 9191, partition: int = 0) -> None:
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


class TestEntityConsumerResilientDeserialize:
    """An un-decodable/poison record must be SKIPPED, not crash-loop the group.

    ``EntityCreatedConsumer`` never overrode ``_handle_message`` at all, so
    before the base-class fix a poison Avro record on
    ``entity.canonical.created.v1`` would wrap into ``MalformedDataError`` and
    dead-letter inline — a burst of them would trip ``dead_letter_cap`` and
    crash-loop the consumer. Note the existing ``MalformedDataError`` raises
    in this file's ``deserialize_value`` (e.g. the JSON-fallback size-cap
    branch) are a DIFFERENT, intentional business-rule dead-letter and are
    NOT covered by this test — this test targets only the raw decode-poison
    path. The skip-and-advance behaviour now lives in
    ``BaseKafkaConsumer._handle_message`` itself
    (``ConsumerConfig.skip_undecodable_records``, default True), so this
    consumer is protected automatically with zero source changes; this test
    guards the regression.
    """

    def test_undecodable_old_schema_record_is_skipped_not_raised(self) -> None:
        from structlog.testing import capture_logs

        consumer = _make_consumer()
        msg = _FakeKafkaMessage(b"\x00garbage-not-avro")
        with (
            patch.object(consumer, "deserialize_value", side_effect=EOFError("short read")),
            capture_logs() as logs,
        ):
            asyncio.run(consumer._handle_message(msg))  # must not raise
        assert any(e["event"] == "kafka_consumer_deserialize_skipped" for e in logs)
        skip = next(e for e in logs if e["event"] == "kafka_consumer_deserialize_skipped")
        assert skip["offset"] == 9191
        assert consumer._dead_letter_count == 0
