"""Unit tests for ConfluentDirectProducer (BP-130 adapter)."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

pytestmark = pytest.mark.unit


class TestConfluentDirectProducer:
    def _make_raw_producer(self) -> MagicMock:
        p = MagicMock()
        p.produce = MagicMock()
        p.flush = MagicMock()
        return p

    def test_produce_bytes_calls_produce_with_correct_args(self) -> None:
        """produce_bytes delegates to producer.produce(topic, value=..., key=...)."""
        from knowledge_graph.infrastructure.messaging.direct_producer import ConfluentDirectProducer

        raw = self._make_raw_producer()
        adapter = ConfluentDirectProducer(raw)

        adapter.produce_bytes(topic="test.topic", key=b"my-key", value=b"my-value")

        raw.produce.assert_called_once_with("test.topic", value=b"my-value", key=b"my-key")

    def test_produce_bytes_does_not_call_flush(self) -> None:
        """produce_bytes must NOT call flush() — blocking flush would stall the event loop."""
        from knowledge_graph.infrastructure.messaging.direct_producer import ConfluentDirectProducer

        raw = self._make_raw_producer()
        adapter = ConfluentDirectProducer(raw)

        adapter.produce_bytes(topic="entity.dirtied.v1", key=b"abc", value=b"payload")

        raw.flush.assert_not_called()

    def test_produce_bytes_passes_bytes_unchanged(self) -> None:
        """produce_bytes does NOT decode or re-encode the bytes payload."""
        from knowledge_graph.infrastructure.messaging.direct_producer import ConfluentDirectProducer

        raw = self._make_raw_producer()
        adapter = ConfluentDirectProducer(raw)
        key = b"\x00\x01binary-key"
        value = b"\xff\xfe\x00raw-avro-bytes"

        adapter.produce_bytes(topic="t", key=key, value=value)

        _, kwargs = raw.produce.call_args
        assert kwargs["key"] is key
        assert kwargs["value"] is value

    def test_implements_direct_kafka_producer_protocol(self) -> None:
        """ConfluentDirectProducer is an instance of DirectKafkaProducerProtocol."""
        from knowledge_graph.application.blocks.graph_write import DirectKafkaProducerProtocol
        from knowledge_graph.infrastructure.messaging.direct_producer import ConfluentDirectProducer

        raw = self._make_raw_producer()
        adapter = ConfluentDirectProducer(raw)

        assert isinstance(adapter, DirectKafkaProducerProtocol)

    def test_multiple_calls_delegate_each_to_produce(self) -> None:
        """Each produce_bytes call results in exactly one producer.produce call."""
        from knowledge_graph.infrastructure.messaging.direct_producer import ConfluentDirectProducer

        raw = self._make_raw_producer()
        adapter = ConfluentDirectProducer(raw)

        adapter.produce_bytes(topic="t1", key=b"k1", value=b"v1")
        adapter.produce_bytes(topic="t2", key=b"k2", value=b"v2")

        assert raw.produce.call_count == 2
        raw.produce.assert_has_calls(
            [
                call("t1", value=b"v1", key=b"k1"),
                call("t2", value=b"v2", key=b"k2"),
            ]
        )
