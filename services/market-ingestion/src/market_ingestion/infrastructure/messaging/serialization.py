"""Avro serialization factories for market-ingestion Kafka events.

Provides:
- ``build_market_ingestion_serializers`` — per-event-type ``AvroSerializer`` mapping.
- ``build_market_ingestion_value_serializer`` — ``OutboxEventValueSerializer`` ready
  to be wired into ``build_serializing_producer`` as ``value_serializer=``.

CRITICAL: Use ``OutboxEventValueSerializer`` (not ``KafkaEventValueSerializer``).
``OutboxEventValueSerializer`` extracts ``value.payload`` (plain dict) before
passing it to the per-type ``AvroSerializer``.  Omitting this causes::

    TypeError: a bytes-like object is required, not 'OutboxKafkaValue'
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from market_ingestion.domain.events import MarketDatasetFetched
from messaging.kafka.producer import OutboxEventValueSerializer  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import serializer_for_schema  # type: ignore[import-untyped]
from messaging.topics import MARKET_DATASET_FETCHED  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroSerializer


def _resolve_schema_path() -> Path:
    relative = Path("infra") / "kafka" / "schemas" / "market.dataset.fetched.avsc"

    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.exists():
            return candidate

    cwd_candidate = Path.cwd() / relative
    if cwd_candidate.exists():
        return cwd_candidate

    msg = "Could not locate market.dataset.fetched.avsc from module path or cwd"
    raise FileNotFoundError(msg)


_SCHEMA_PATH: Path = _resolve_schema_path()


def _schema_str() -> str:
    """Read and return the Avro schema JSON string."""
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def build_market_ingestion_serializers(
    registry_client: SchemaRegistryClient,
) -> dict[str, AvroSerializer]:
    """Build per-event-type Avro serializer mapping.

    Returns a dict suitable for use with ``OutboxEventValueSerializer``::

        serializers = build_market_ingestion_serializers(registry)
        value_ser = OutboxEventValueSerializer(serializers)

    Args:
        registry_client: Connected Confluent ``SchemaRegistryClient``.

    Returns:
        ``{event_type: AvroSerializer}`` mapping for all market-ingestion events.
    """
    schema = _schema_str()
    # D-005: Only MarketDatasetFetched is published to the outbox (cross-service event).
    # IngestionTaskCompleted and IngestionTaskScheduled are internal state transitions —
    # they are NOT written to the outbox and have no Avro schema.
    return {
        MarketDatasetFetched.EVENT_TYPE: serializer_for_schema(schema, registry_client),
    }


def build_market_ingestion_value_serializer(
    registry_client: SchemaRegistryClient,
) -> OutboxEventValueSerializer:
    """Build an ``OutboxEventValueSerializer`` for market-ingestion events.

    Wire it into ``build_serializing_producer`` via ``value_serializer=``::

        producer = build_serializing_producer(
            config,
            value_serializer=build_market_ingestion_value_serializer(registry),
        )

    CRITICAL: pass ``value_serializer=`` explicitly; omitting it leaves the
    ``SerializingProducer`` without a serializer and causes a silent bytes error
    on first dispatch.

    Args:
        registry_client: Connected Confluent ``SchemaRegistryClient``.

    Returns:
        ``OutboxEventValueSerializer`` keyed on ``market.dataset.fetched``.
    """
    serializers = build_market_ingestion_serializers(registry_client)
    return OutboxEventValueSerializer(serializers)


# Topic name constant (re-exported for convenience)
MARKET_INGESTION_TOPIC: str = MARKET_DATASET_FETCHED
