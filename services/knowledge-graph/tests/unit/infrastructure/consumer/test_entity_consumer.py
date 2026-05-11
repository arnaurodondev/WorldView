"""Unit tests for EntityCreatedConsumer Avro deserialization (PLAN-0062 Wave A).

Tests:
  - test_decodes_confluent_avro_payload — round-trip through serialize_confluent_avro
  - test_falls_back_to_json_for_legacy_payload — pre-PLAN-0062 JSON payload still accepted
"""

from __future__ import annotations

from unittest.mock import MagicMock

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
