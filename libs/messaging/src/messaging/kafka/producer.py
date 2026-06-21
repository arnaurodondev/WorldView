"""Kafka producer configuration, value types, and factory.

:class:`KafkaProducerConfig` sets production-safe defaults (``acks=all``,
``enable.idempotence=true``).  :func:`build_serializing_producer` wraps the
Confluent ``SerializingProducer`` with sensible configuration.
"""

from __future__ import annotations

import dataclasses
import os
from typing import TYPE_CHECKING, Any

from messaging.kafka_config import apply_base_rdkafka_config

if TYPE_CHECKING:
    from confluent_kafka import SerializingProducer
    from confluent_kafka.schema_registry.avro import AvroSerializer


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back to *default*.

    Producers are constructed deep inside outbox dispatchers that do not all
    thread pydantic-settings through to ``KafkaProducerConfig``.  Reading the
    handful of connection-resilience knobs straight from the environment (with
    safe in-code defaults) keeps these tunable per-deployment without plumbing
    a new setting through every dispatcher call site, while staying consistent
    with the dataclass-as-config style of this module.  A malformed value is
    ignored in favour of the default so a typo can never wedge startup.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


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
        socket_connection_setup_timeout_ms: Max time for a single TCP+broker
            connection setup before librdkafka aborts and retries it.
        request_timeout_ms: Per-request (incl. Metadata/ApiVersion) timeout.
        reconnect_backoff_ms / reconnect_backoff_max_ms: Reconnect backoff
            envelope after a connection drops.
        metadata_max_age_ms: How often metadata is proactively refreshed so a
            stale leader is re-resolved.
        connections_max_idle_ms: Idle-connection reaper window (0 = disabled).
    """

    bootstrap_servers: str = "localhost:9092"
    acks: str = "all"
    enable_idempotence: bool = True
    compression_type: str = "snappy"
    linger_ms: int = 5
    batch_size: int = 16_384
    retries: int = 5
    # PLAN-0109 F-1-03: raised from 30_000 to 120_000 so retries actually
    # complete after a macOS host-sleep TCP-stale event (BP-661).  See
    # ``libs/messaging/src/messaging/kafka_config.py`` for the full keep-alive
    # tuning rationale.
    delivery_timeout_ms: int = 120_000

    # ── PLAN-0113-adjacent: producer connection-resilience override (BP-704) ──
    #
    # Failure signature: the outbox dispatcher wedges with rdkafka
    # ``MetadataRequest``/``ApiVersionRequest`` timeouts and
    # ``Connection setup timed out in state CONNECT (after ~31000ms)`` to
    # ``kafka:29092``, never recovering without a container restart (~every
    # 10 min under load).  ~31s == librdkafka's *default*
    # ``socket.connection.setup.timeout.ms`` (30s) + jitter.  The shared base
    # config (``messaging.kafka_config._BASE_RDKAFKA_CONFIG``, owned by the
    # consumer/reconnect workstream) still pins the slow 30s defaults.  Rather
    # than edit that contended shared surface, the producer carries its OWN
    # faster connection knobs here; because ``apply_base_rdkafka_config`` lets
    # producer keys win on collision (base spread first, these spread on top),
    # these override the slow base values for producers only.
    #
    # Each value is env-overridable so a deployment can re-tune without a code
    # change.  Defaults are chosen so a lost connection re-establishes in
    # *seconds*, not the 31s-then-wedge we observe today.
    socket_connection_setup_timeout_ms: int = dataclasses.field(
        # 10s (vs librdkafka 30s default): a CONNECT that hasn't completed the
        # TCP+ApiVersion handshake in 10s is almost certainly a dead/stale
        # endpoint -- abort fast and let reconnect re-resolve, instead of
        # holding the producer hostage for ~31s while in-flight produces stall.
        default_factory=lambda: _env_int("KAFKA_PRODUCER_CONN_SETUP_TIMEOUT_MS", 10_000),
    )
    request_timeout_ms: int = dataclasses.field(
        # 20s ceiling on a single produce/Metadata/ApiVersion request so a
        # half-broken broker surfaces an error (which drives a reconnect)
        # quickly.  Must stay <= delivery.timeout.ms (120s) so retries fit.
        default_factory=lambda: _env_int("KAFKA_PRODUCER_REQUEST_TIMEOUT_MS", 20_000),
    )
    reconnect_backoff_ms: int = dataclasses.field(
        # Start reconnecting almost immediately (250ms) so a transient blip
        # heals in well under a second.
        default_factory=lambda: _env_int("KAFKA_PRODUCER_RECONNECT_BACKOFF_MS", 250),
    )
    reconnect_backoff_max_ms: int = dataclasses.field(
        # Cap the exponential reconnect backoff at 5s so a persistently flaky
        # broker is retried at least every 5s -- no minutes-long dead air.
        default_factory=lambda: _env_int("KAFKA_PRODUCER_RECONNECT_BACKOFF_MAX_MS", 5_000),
    )
    metadata_max_age_ms: int = dataclasses.field(
        # Proactively refresh metadata every 60s (vs base 180s) so a leader
        # change / stale topic-leader mapping is re-resolved fast -- directly
        # targets the repeated MetadataRequest-timeout symptom.
        default_factory=lambda: _env_int("KAFKA_PRODUCER_METADATA_MAX_AGE_MS", 60_000),
    )
    connections_max_idle_ms: int = dataclasses.field(
        # Proactively close idle connections after 4 min so the producer never
        # tries to reuse a connection the broker/LB has already silently
        # reaped (a common source of the "first produce after quiet wedges"
        # variant).  Kept just under typical broker/LB idle windows.
        default_factory=lambda: _env_int("KAFKA_PRODUCER_CONNECTIONS_MAX_IDLE_MS", 240_000),
    )

    def to_dict(self) -> dict[str, Any]:
        """Return Confluent-compatible config dict.

        PLAN-0093 Wave A-2 (F-LOG-003): the rdkafka base config
        (``broker.address.ttl=30000`` + ``broker.address.family=v4``) is
        merged in first via :func:`apply_base_rdkafka_config`, then the
        producer's own keys are spread on top so a future per-producer
        override still wins.  The connection-resilience keys below (BP-704)
        deliberately rely on that ordering to override the slower 30s defaults
        the shared base still carries for consumers.
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
                # Producer connection-resilience overrides (BP-704) -- win over
                # the slow base defaults because they are spread on top here.
                "socket.connection.setup.timeout.ms": self.socket_connection_setup_timeout_ms,
                "request.timeout.ms": self.request_timeout_ms,
                "reconnect.backoff.ms": self.reconnect_backoff_ms,
                "reconnect.backoff.max.ms": self.reconnect_backoff_max_ms,
                "metadata.max.age.ms": self.metadata_max_age_ms,
                "connections.max.idle.ms": self.connections_max_idle_ms,
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
