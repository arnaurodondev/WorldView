"""ConfluentDirectProducer — adapter that satisfies DirectKafkaProducerProtocol.

``confluent_kafka.Producer`` exposes ``produce(topic, value, key, ...)`` but
does NOT have a ``produce_bytes(*, topic, key, value)`` method.  The graph
write blocks (Block 12a and related workers) call ``produce_bytes`` via the
structural ``DirectKafkaProducerProtocol``; without this adapter they raise
``AttributeError`` at runtime (BP-130).

Usage::

    from confluent_kafka import Producer
    from knowledge_graph.infrastructure.messaging.direct_producer import ConfluentDirectProducer

    raw_producer = Producer({"bootstrap.servers": bootstrap_servers})
    direct_producer = ConfluentDirectProducer(raw_producer)

Notes
-----
  - ``produce_bytes`` calls ``Producer.produce(topic, value=value, key=key)``
    WITHOUT ``flush()``.  librdkafka enqueues the message to its internal
    buffer and delivers it in the background.  Calling ``flush()`` here would
    block the asyncio event loop.
  - Delivery is best-effort (fire-and-forget).  ``entity.dirtied.v1`` is a
    compacted topic where the last message per key wins; a missed delivery
    means the entity is not re-embedded until the next state change triggers
    another produce — an acceptable trade-off (see PRD-0018 §6 Worker 13D-7).

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from knowledge_graph.application.blocks.graph_write import DirectKafkaProducerProtocol

if TYPE_CHECKING:
    from confluent_kafka import Producer  # type: ignore[import-untyped]


class ConfluentDirectProducer(DirectKafkaProducerProtocol):
    """Adapter: wraps ``confluent_kafka.Producer`` to satisfy ``DirectKafkaProducerProtocol``.

    Args:
    ----
        producer: An initialised ``confluent_kafka.Producer`` instance.

    """

    def __init__(self, producer: Producer) -> None:
        self._producer = producer

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None:
        """Enqueue *value* to *topic* in the librdkafka internal buffer.

        Non-blocking — does NOT call ``flush()``.  Delivery is asynchronous
        via librdkafka's background producer thread.

        Args:
        ----
            topic: Kafka topic name.
            key:   Message key bytes (used for compacted-topic dedup).
            value: Message value bytes (raw Avro or JSON).

        """
        self._producer.produce(topic, value=value, key=key)
