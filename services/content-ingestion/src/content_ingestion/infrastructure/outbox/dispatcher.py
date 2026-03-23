"""Outbox dispatcher: polls outbox_events, serialises to Avro, publishes to Kafka."""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING, Any

import fastavro  # type: ignore[import-untyped]
import structlog

from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.session import get_db_session
from content_ingestion.infrastructure.outbox.avro_schema import ARTICLE_RAW_V1_SCHEMA

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from content_ingestion.config import Settings
    from content_ingestion.infrastructure.db.models import OutboxEventModel

logger = structlog.get_logger(__name__)


class OutboxDispatcher:
    """Polls outbox_events, serialises to Avro, publishes to Kafka."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        kafka_producer: Any,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._kafka_producer = kafka_producer
        self._settings = settings

    async def run_once(self) -> None:
        async with get_db_session(self._session_factory) as session:
            repo = OutboxRepository(session)
            events = await repo.fetch_pending(limit=self._settings.OUTBOX_BATCH_SIZE)
        for event in events:
            await self._dispatch_event(event)

    async def _dispatch_event(self, event: OutboxEventModel) -> None:
        try:
            avro_bytes = self._serialize(event.payload)
            await self._kafka_producer.send_and_wait(
                self._settings.KAFKA_OUTBOX_TOPIC,
                value=avro_bytes,
                key=str(event.aggregate_id).encode(),
            )
            async with get_db_session(self._session_factory) as session:
                await OutboxRepository(session).mark_dispatched(event.id)
            logger.info("outbox.dispatched", event_id=str(event.id))
        except Exception as exc:
            logger.error("outbox.dispatch_failed", event_id=str(event.id), error=str(exc))
            async with get_db_session(self._session_factory) as session:
                repo = OutboxRepository(session)
                await repo.mark_failed(event.id, str(exc))
                updated = await repo.get_by_id(event.id)
                if updated is not None and updated.retry_count >= self._settings.MAX_RETRIES:
                    await repo.move_to_dlq(event.id)

    def _serialize(self, payload: dict) -> bytes:
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, ARTICLE_RAW_V1_SCHEMA, payload)
        return buf.getvalue()

    async def run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as exc:
                logger.error("outbox.loop_error", error=str(exc))
            await asyncio.sleep(self._settings.OUTBOX_POLL_INTERVAL_SECONDS)
