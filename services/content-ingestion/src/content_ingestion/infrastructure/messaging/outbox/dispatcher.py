"""Content-ingestion outbox dispatcher — extends BaseOutboxDispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from content_ingestion.infrastructure.messaging.outbox.unit_of_work import SqlAlchemyUnitOfWork
from messaging.kafka.dispatcher.base import BaseOutboxDispatcher, DispatcherConfig
from messaging.kafka.producer import KafkaProducerConfig, OutboxEventValueSerializer, build_serializing_producer
from messaging.kafka.serializer import AvroSerializerConfig, build_avro_serializer
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from content_ingestion.config import Settings
    from messaging.kafka.dispatcher.base import UnitOfWorkWithOutboxProtocol

_SCHEMA_DIR = Path(__file__).parent.parent / "schemas"
logger = get_logger(__name__)


class ContentIngestionOutboxDispatcher(BaseOutboxDispatcher):
    """Transactional outbox dispatcher for the content-ingestion service (S4).

    Extends BaseOutboxDispatcher to provide:
    - SQLAlchemy unit-of-work with lease-based outbox repository
    - Confluent SerializingProducer with Schema Registry Avro serialization
    - Schema loaded from .avsc file (not a Python dict)
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
        """Return the Avro value serializer for a given event type.

        The ``OutboxEventValueSerializer`` multiplexes per-topic serializers
        internally, so this method delegates to the shared instance.  The
        ``event_type`` parameter is accepted for interface compatibility with
        ``BaseOutboxDispatcher`` but is not used for routing here — the
        serializer routes based on the ``topic`` field of each outbox record.
        """
        return self._get_value_serializer()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_schema_registry_client(self) -> SchemaRegistryClient:
        from confluent_kafka.schema_registry import SchemaRegistryClient

        conf: dict[str, Any] = {"url": self._settings.kafka_schema_registry_url}
        if self._settings.kafka_schema_registry_basic_auth:
            conf["basic.auth.user.info"] = self._settings.kafka_schema_registry_basic_auth
        return SchemaRegistryClient(conf)

    def _get_value_serializer(self) -> OutboxEventValueSerializer:
        if self._value_serializer is None:
            registry = self._build_schema_registry_client()
            ser_config = AvroSerializerConfig(auto_register_schemas=True)

            article_schema_str = json.dumps(json.loads((_SCHEMA_DIR / "content.article.raw.v1.avsc").read_text()))
            article_ser = build_avro_serializer(schema_str=article_schema_str, registry=registry, config=ser_config)

            prediction_schema_str = json.dumps(json.loads((_SCHEMA_DIR / "market.prediction.v1.avsc").read_text()))
            prediction_ser = build_avro_serializer(
                schema_str=prediction_schema_str, registry=registry, config=ser_config
            )

            # PLAN-0086 Wave E-2: add serializer for the tenant document deleted event.
            # The topic name matches the outbox ``topic`` column written by
            # ``DeleteTenantDocumentUseCase``.
            deleted_schema_str = json.dumps(json.loads((_SCHEMA_DIR / "content.document.deleted.v1.avsc").read_text()))
            deleted_ser = build_avro_serializer(schema_str=deleted_schema_str, registry=registry, config=ser_config)

            # PLAN-0056 Wave B3: serializers for the 4 deeper Polymarket streams.
            # The OutboxEventValueSerializer routes on the outbox ``event_type``
            # column (not the topic), so keys are the event_type discriminators
            # emitted by FetchAndWritePredictionStreamUseCase.
            def _load(name: str) -> Any:
                schema_str = json.dumps(json.loads((_SCHEMA_DIR / name).read_text()))
                return build_avro_serializer(schema_str=schema_str, registry=registry, config=ser_config)

            event_ser = _load("market.prediction.event.v1.avsc")
            history_ser = _load("market.prediction.history.v1.avsc")
            trade_ser = _load("market.prediction.trade.v1.avsc")
            oi_ser = _load("market.prediction.oi.v1.avsc")

            self._value_serializer = OutboxEventValueSerializer(
                {
                    "content.article.raw.v1": article_ser,
                    "market.prediction.snapshot": prediction_ser,
                    "content.document.deleted.v1": deleted_ser,
                    "market.prediction.event": event_ser,
                    "market.prediction.history": history_ser,
                    "market.prediction.trade": trade_ser,
                    "market.prediction.oi": oi_ser,
                }
            )
        return self._value_serializer
