"""Concrete OutboxDispatcher for the Portfolio service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from messaging.kafka.dispatcher.base import BaseOutboxDispatcher, DispatcherConfig  # type: ignore[import-untyped]
from messaging.kafka.producer import (  # type: ignore[import-untyped]
    KafkaProducerConfig,
    OutboxEventValueSerializer,
    build_serializing_producer,
)
from messaging.kafka.schema_registry import (  # type: ignore[import-untyped]
    SchemaRegistryConfig,
    build_schema_registry_client,
)
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.infrastructure.messaging.serialization import build_outbox_event_serializers, headers_for_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from portfolio.config import Settings


class OutboxDispatcher(BaseOutboxDispatcher):
    """Concrete outbox dispatcher wired to the portfolio Kafka topic."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        config: DispatcherConfig | None = None,
    ) -> None:
        super().__init__(config=config)
        self._settings = settings
        self._session_factory = session_factory
        self._producer: Any = None
        self._serializers: dict[str, Any] = {}

    def _build_producer(self) -> Any:
        registry_config = SchemaRegistryConfig(
            url=self._settings.kafka_schema_registry_url,
            basic_auth_user_info=self._settings.kafka_schema_registry_basic_auth,
        )
        registry_client = build_schema_registry_client(registry_config)
        self._serializers = build_outbox_event_serializers(registry_client)

        producer_config = KafkaProducerConfig(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
        )
        value_serializer = OutboxEventValueSerializer(self._serializers)
        return build_serializing_producer(producer_config, value_serializer=value_serializer)

    def get_producer(self) -> Any:
        if self._producer is None:
            self._producer = self._build_producer()
        return self._producer

    def get_serializer(self, event_type: str) -> Any:
        return self._serializers.get(event_type)

    async def get_unit_of_work(self) -> Any:
        from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork  # type: ignore[import-untyped]

        return SqlAlchemyUnitOfWork(self._session_factory)


def create_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    config: DispatcherConfig | None = None,
) -> OutboxDispatcher:
    """Factory for OutboxDispatcher."""
    if config is None:
        config = DispatcherConfig(
            poll_interval_seconds=settings.dispatcher_poll_interval_seconds,
            lease_seconds=settings.dispatcher_lease_seconds,
            batch_size=settings.dispatcher_immediate_batch_size,
            max_attempts=settings.dispatcher_max_attempts,
            initial_backoff_seconds=settings.dispatcher_backoff_base_seconds,
        )
    return OutboxDispatcher(settings=settings, session_factory=session_factory, config=config)


__all__ = ["OutboxDispatcher", "create_dispatcher"]
# Suppress unused import warning — headers_for_event is part of this module's public surface
_ = headers_for_event, EVENT_TOPIC_MAP
