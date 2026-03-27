"""Kafka consumer for content.article.raw.v1 events.

Consumes raw article events from S4, delegates to ProcessArticleUseCase,
and commits offsets AFTER DB commit (at-least-once delivery).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from content_store.application.use_cases.process_article import (
    ProcessArticleUseCase,
    RawArticleEvent,
)
from content_store.infrastructure.db.repositories.dedup import DedupHashRepository
from content_store.infrastructure.db.repositories.document import DocumentRepository
from content_store.infrastructure.db.repositories.minhash import MinHashRepository
from content_store.infrastructure.db.repositories.outbox import OutboxRepository
from content_store.infrastructure.metrics.prometheus import s5_lsh_index_failures_total

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from content_store.config import Settings
    from content_store.infrastructure.valkey.lsh_client import ValkeyLSHClient
    from storage.interface import ObjectStorage

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


def _parse_raw_event(value: dict[str, Any]) -> RawArticleEvent:
    """Parse a deserialized Avro dict into a RawArticleEvent."""
    return RawArticleEvent(
        event_id=str(value["event_id"]),
        doc_id=str(value["doc_id"]),
        source_type=str(value["source_type"]),
        source_url=value.get("source_url"),
        minio_bronze_key=str(value["minio_bronze_key"]),
        content_hash=str(value["content_hash"]),
        title=value.get("title"),
        published_at=value.get("published_at"),
        is_backfill=bool(value.get("is_backfill", False)),
    )


class ArticleConsumerConfig:
    """Configuration for the ArticleConsumer."""

    def __init__(self, settings: Settings) -> None:
        self.bootstrap_servers = settings.kafka_bootstrap_servers
        self.group_id = settings.kafka_consumer_group
        self.input_topic = settings.kafka_input_topic
        self.output_topic = settings.kafka_output_topic
        self.bronze_bucket = settings.minio_bronze_bucket
        self.silver_bucket = settings.minio_silver_bucket
        self.num_perm = settings.minhash_num_perm


class ArticleConsumer:
    """Kafka consumer for content.article.raw.v1.

    Consumes messages, delegates processing to ProcessArticleUseCase,
    and commits offsets after successful DB commit. At-least-once delivery
    with idempotent dedup via Stage A raw hash check.
    """

    def __init__(
        self,
        *,
        config: ArticleConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        object_store: ObjectStorage,
        lsh_client: ValkeyLSHClient,
    ) -> None:
        self._config = config
        self._session_factory = session_factory
        self._store = object_store
        self._lsh = lsh_client
        self._stop_event = asyncio.Event()

    async def process_message(self, value: dict[str, Any]) -> None:
        """Process a single deserialized Avro message.

        Opens a new session for each message, ensuring atomic DB writes.
        Idempotency is ensured by Stage A raw hash check (content_hash
        UNIQUE constraint) and Stage B normalized hash check.

        Args:
            value: Deserialized content.article.raw.v1 Avro dict.
        """
        article = _parse_raw_event(value)
        log = logger.bind(event_id=article.event_id, doc_id=article.doc_id)

        async with self._session_factory() as session:
            try:
                use_case = ProcessArticleUseCase(
                    session=session,
                    document_repo=DocumentRepository(session),
                    dedup_repo=DedupHashRepository(session),
                    minhash_repo=MinHashRepository(session),
                    outbox_repo=OutboxRepository(session),
                    object_store=self._store,
                    bronze_bucket=self._config.bronze_bucket,
                    silver_bucket=self._config.silver_bucket,
                    lsh_client=self._lsh,
                    output_topic=self._config.output_topic,
                    num_perm=self._config.num_perm,
                )

                summary = await use_case.execute(article)

                # Commit the DB transaction BEFORE acknowledging offset
                await session.commit()

                # Index in LSH AFTER commit — best-effort (CR-3 fix)
                if summary.signature is not None and summary.doc_id is not None:
                    try:
                        await self._lsh.index(
                            summary.doc_id,
                            summary.signature,
                            summary.source_type or article.source_type,
                            summary.source_type or article.source_type,
                        )
                    except Exception:
                        s5_lsh_index_failures_total.inc()
                        log.error("lsh_index_failed", doc_id=str(summary.doc_id))

                log.info(
                    "article_processed",
                    suppressed=summary.suppressed,
                    decision=summary.decision.outcome,
                    doc_id=str(summary.doc_id) if summary.doc_id else None,
                )
            except Exception:
                await session.rollback()
                log.exception("article_processing_failed")
                raise

    def stop(self) -> None:
        """Signal the consumer to stop."""
        self._stop_event.set()
