"""Content-store outbox dispatcher — publishes content.article.stored.v1 events.

Extends BaseOutboxDispatcher following BP-001: uses OutboxEventValueSerializer
(not KafkaEventValueSerializer) for correct Avro serialization.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from content_store.infrastructure.messaging.outbox.unit_of_work import SqlAlchemyUnitOfWork
from messaging.kafka.dispatcher.base import BaseOutboxDispatcher, DispatcherConfig
from messaging.kafka.producer import (
    KafkaProducerConfig,
    OutboxEventValueSerializer,
    build_serializing_producer,
)
from messaging.kafka.serializer import AvroSerializerConfig, build_avro_serializer
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from content_store.config import Settings
    from messaging.kafka.dispatcher.base import UnitOfWorkWithOutboxProtocol


def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    msg = f"Could not locate infra/kafka/schemas/ from {__file__}"
    raise FileNotFoundError(msg)


_SCHEMA_DIR = _find_schema_dir()
logger = get_logger(__name__)


class ContentStoreOutboxDispatcher(BaseOutboxDispatcher):
    """Transactional outbox dispatcher for the content-store service (S5).

    Extends BaseOutboxDispatcher to provide:
    - SQLAlchemy unit-of-work with lease-based outbox repository
    - Confluent SerializingProducer with Schema Registry Avro serialization
    - Uses OutboxEventValueSerializer (guard BP-001)
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        config = DispatcherConfig(
            poll_interval_seconds=settings.outbox_poll_interval_seconds,
            lease_seconds=settings.outbox_lease_seconds,
            batch_size=settings.outbox_batch_size,
            max_attempts=settings.outbox_max_attempts,
        )
        super().__init__(config)
        self._settings = settings
        self._session_factory = session_factory
        self._producer: Any = None
        self._value_serializer: OutboxEventValueSerializer | None = None

    # ── Required by BaseOutboxDispatcher ─────────────────────────────────────

    async def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
        return cast("UnitOfWorkWithOutboxProtocol", SqlAlchemyUnitOfWork(self._session_factory))

    def get_producer(self) -> Any:
        if self._producer is None:
            value_serializer = self._get_value_serializer()
            self._producer = build_serializing_producer(
                config=KafkaProducerConfig(
                    bootstrap_servers=self._settings.kafka_bootstrap_servers,
                ),
                value_serializer=value_serializer,
            )
        return self._producer

    def get_serializer(self, event_type: str) -> Any:
        # Serialization handled by OutboxEventValueSerializer on the producer
        return self._get_value_serializer()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_schema_registry_client(self) -> SchemaRegistryClient:
        from confluent_kafka.schema_registry import SchemaRegistryClient

        conf: dict[str, Any] = {"url": self._settings.schema_registry_url}
        return SchemaRegistryClient(conf)

    def _get_value_serializer(self) -> OutboxEventValueSerializer:
        if self._value_serializer is None:
            schema_path = _SCHEMA_DIR / "content.article.stored.v1.avsc"
            schema_str = json.dumps(json.loads(schema_path.read_text()))
            registry = self._build_schema_registry_client()
            avro_ser = build_avro_serializer(
                schema_str=schema_str,
                registry=registry,
                config=AvroSerializerConfig(auto_register_schemas=True),
            )
            self._value_serializer = OutboxEventValueSerializer(
                {"content.article.stored.v1": avro_ser},
            )
        return self._value_serializer
