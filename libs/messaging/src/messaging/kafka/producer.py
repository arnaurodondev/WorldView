"""Kafka producer configuration, value types, and factory.

:class:`KafkaProducerConfig` sets production-safe defaults (``acks=all``,
``enable.idempotence=true``).  :func:`build_serializing_producer` wraps the
Confluent ``SerializingProducer`` with sensible configuration.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from messaging.kafka_config import apply_base_rdkafka_config

if TYPE_CHECKING:
    from confluent_kafka import SerializingProducer
    from confluent_kafka.schema_registry.avro import AvroSerializer


@dataclasses.dataclass
class KafkaProducerConfig:
    """Typed configuration for a Confluent :class:`SerializingProducer`.

    Args:
        bootstrap_servers: Comma-separated broker addresses.
        acks: Acknowledgement mode.  ``"all"`` enables full ISR ack.
        enable_idempotence: Prevents duplicate messages on retry.
        compression_type: Message compression codec.
        linger_ms: Delay to allow batching (ms).
        batch_size: Maximum batch size in bytes.
        retries: Number of internal producer retries.
        delivery_timeout_ms: Upper bound on delivery time (ms).
    """

    bootstrap_servers: str = "localhost:9092"
    acks: str = "all"
    enable_idempotence: bool = True
    compression_type: str = "snappy"
    linger_ms: int = 5
    batch_size: int = 16_384
    retries: int = 5
    delivery_timeout_ms: int = 30_000

    def to_dict(self) -> dict[str, Any]:
        """Return Confluent-compatible config dict.

        PLAN-0093 Wave A-2 (F-LOG-003): the rdkafka base config
        (``broker.address.ttl=30000`` + ``broker.address.family=v4``) is
        merged in first via :func:`apply_base_rdkafka_config`, then the
        producer's own keys are spread on top so a future per-producer
        override still wins.
        """
        return apply_base_rdkafka_config(
            {
                "bootstrap.servers": self.bootstrap_servers,
                "acks": self.acks,
                "enable.idempotence": self.enable_idempotence,
                "compression.type": self.compression_type,
                "linger.ms": self.linger_ms,
                "batch.size": self.batch_size,
                "retries": self.retries,
                "delivery.timeout.ms": self.delivery_timeout_ms,
            }
        )


@dataclasses.dataclass
class OutboxKafkaValue:
    """Structured value for outbox-originated Kafka messages.

    Args:
        event_type: Stable event type string (e.g. ``market.dataset.fetched``).
        payload: Serializable event payload dict.
    """

    event_type: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return Avro-compatible dict."""
        return {"event_type": self.event_type, "payload": self.payload}


class KafkaEventValueSerializer:
    """Routes domain events to the correct :class:`AvroSerializer` by event type.

    Args:
        serializers: Mapping of ``event_type`` → :class:`AvroSerializer`.
    """

    def __init__(self, serializers: dict[str, AvroSerializer]) -> None:
        self._serializers = serializers

    def __call__(self, value: Any, ctx: Any) -> bytes | None:
        """Serialize *value* using the serializer registered for its event type.

        Args:
            value: Domain event implementing the
                :class:`~messaging.kafka.serializer.AvroDictable` protocol.
            ctx: :class:`confluent_kafka.serialization.SerializationContext`.

        Returns:
            Serialized bytes, or ``None`` if *value* is ``None``.
        """
        if value is None:
            return None
        event_type: str = value.event_type
        serializer = self._serializers.get(event_type)
        if serializer is None:
            msg = f"No serializer registered for event_type={event_type!r}"
            raise KeyError(msg)
        return serializer(value, ctx)  # type: ignore[no-any-return]


class OutboxEventValueSerializer(KafkaEventValueSerializer):
    """Serializer for :class:`OutboxKafkaValue` messages dispatched via outbox."""

    def __call__(self, value: Any, ctx: Any) -> bytes | None:
        """Serialize *value* by extracting its payload and routing to the
        per-event-type AvroSerializer.

        Args:
            value: :class:`OutboxKafkaValue` carrying event_type and payload.
            ctx: :class:`confluent_kafka.serialization.SerializationContext`.

        Returns:
            Serialized bytes, or ``None`` if *value* is ``None``.
        """
        if value is None:
            return None
        event_type: str = value.event_type
        serializer = self._serializers.get(event_type)
        if serializer is None:
            msg = f"No serializer registered for event_type={event_type!r}"
            raise KeyError(msg)
        return serializer(value.payload, ctx)  # type: ignore[no-any-return]


def build_serializing_producer(
    config: KafkaProducerConfig,
    key_serializer: Any | None = None,
    value_serializer: Any | None = None,
) -> SerializingProducer:
    """Construct a Confluent :class:`SerializingProducer`.

    Args:
        config: Producer configuration.
        key_serializer: Callable for key serialization (optional).
        value_serializer: Callable for value serialization (optional).

    Returns:
        Configured :class:`SerializingProducer` instance.
    """
    from confluent_kafka import SerializingProducer

    producer_conf = config.to_dict()
    if key_serializer is not None:
        producer_conf["key.serializer"] = key_serializer
    if value_serializer is not None:
        producer_conf["value.serializer"] = value_serializer

    return SerializingProducer(producer_conf)
