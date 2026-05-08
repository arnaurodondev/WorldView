"""Kafka consumer for content.article.raw.v1 events.

Extends BaseKafkaConsumer[dict] from libs/messaging for standardised
poll-loop, idempotency, retry/DLQ routing, and metrics.

Idempotency: processed_events table (event_id UUID PK).
DLQ: dead_letter() writes directly to dead_letter_queue via a new session.
CR-3: LSH indexing happens AFTER DB commit in _handle_message override.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import structlog

from content_store.application.use_cases.process_article import (
    ProcessArticleUseCase,
    ProcessingSummary,
    RawArticleEvent,
)
from content_store.domain.errors import BronzeObjectNotFoundError
from content_store.infrastructure.db.repositories.dedup import DedupHashRepository
from content_store.infrastructure.db.repositories.document import DocumentRepository
from content_store.infrastructure.db.repositories.minhash import MinHashRepository
from content_store.infrastructure.db.repositories.outbox import OutboxRepository
from content_store.infrastructure.db.repositories.processed_events import ProcessedEventsRepository
from content_store.infrastructure.metrics.prometheus import (
    record_processing_outcome,
    s5_lsh_index_failures_total,
)
from content_store.infrastructure.storage.minio_bronze import BronzeStorageAdapter
from content_store.infrastructure.storage.minio_silver import SilverStorageAdapter
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from content_store.config import Settings
    from content_store.infrastructure.valkey.lsh_client import ValkeyLSHClient
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


_SCHEMA_DIR = find_schema_dir()
_INPUT_TOPIC = "content.article.raw.v1"


# ── Unit of Work ──────────────────────────────────────────────────────────────


class _SessionUnitOfWork(UnitOfWorkProtocol):
    """SQLAlchemy AsyncSession wrapper implementing UnitOfWorkProtocol.

    Opened on ``__aenter__`` and closed on ``__aexit__``.
    The ``session`` attribute is available to the consumer's abstract method
    implementations after ``__aenter__`` has been called.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.session: AsyncSession | None = None
        self._session_cm: Any = None

    async def __aenter__(self) -> _SessionUnitOfWork:
        self._session_cm = self._session_factory()
        self.session = await self._session_cm.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(*args)

    async def commit(self) -> None:
        if self.session is not None:
            await self.session.commit()

    async def rollback(self) -> None:
        if self.session is not None:
            await self.session.rollback()


# ── Config ────────────────────────────────────────────────────────────────────


class ArticleConsumerConfig:
    """S5-specific consumer configuration.

    Holds application-level settings (buckets, topics, perm count) separate
    from the transport-level ``ConsumerConfig`` passed to ``BaseKafkaConsumer``.
    """

    def __init__(self, settings: Settings) -> None:
        self.bootstrap_servers = settings.kafka_bootstrap_servers
        self.group_id = settings.kafka_consumer_group
        self.input_topic = settings.kafka_input_topic
        self.output_topic = settings.kafka_output_topic
        self.bronze_bucket = settings.minio_bronze_bucket
        self.silver_bucket = settings.minio_silver_bucket
        self.num_perm = settings.minhash_num_perm


# ── Helper ────────────────────────────────────────────────────────────────────


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
        # PLAN-0086 Wave C-1: propagate tenant_id from the Avro event envelope.
        # None = public/global news; non-None = private tenant content.
        tenant_id=value.get("tenant_id") or None,
    )


# ── Consumer ──────────────────────────────────────────────────────────────────


class ArticleConsumer(BaseKafkaConsumer[dict]):  # type: ignore[type-arg]
    """Kafka consumer for content.article.raw.v1.

    Extends BaseKafkaConsumer[dict] (libs/messaging) for standardised
    poll-loop, idempotency via processed_events, and retry/DLQ routing.

    CR-3 compliance: LSH indexing is deferred to AFTER the DB commit
    by overriding _handle_message (see below).
    """

    def __init__(
        self,
        *,
        config: ArticleConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        object_store: ObjectStorage,
        lsh_client: ValkeyLSHClient,
    ) -> None:
        consumer_config = ConsumerConfig(
            bootstrap_servers=config.bootstrap_servers,
            group_id=config.group_id,
            topics=[config.input_topic],
        )
        super().__init__(consumer_config)
        self._app_config = config
        self._session_factory = session_factory
        self._store = object_store
        self._lsh = lsh_client
        self._current_uow: _SessionUnitOfWork | None = None
        self._current_summary: ProcessingSummary | None = None
        # R24: bronze bytes pre-fetched in _handle_message BEFORE the DB session opens.
        # Stored on self so process_message() can pass them to the use case.
        self._prefetched_bytes: bytes | None = None

    # ── Abstract: dedup ───────────────────────────────────────────────────────

    async def is_duplicate(self, event_id: str) -> bool:
        """Check processed_events table for prior processing of *event_id*.

        Uses the current UoW session when available (avoids a second session).
        Falls back to a fresh session if called outside a UoW context.
        """
        if self._current_uow is not None and self._current_uow.session is not None:
            repo = ProcessedEventsRepository(self._current_uow.session)
            return await repo.is_duplicate(event_id)
        # Fallback: standalone check (e.g., called from retry path)
        async with self._session_factory() as session:
            return await ProcessedEventsRepository(session).is_duplicate(event_id)

    async def mark_processed(self, event_id: str) -> None:
        """Insert *event_id* into processed_events inside the current UoW."""
        assert self._current_uow is not None and self._current_uow.session is not None
        repo = ProcessedEventsRepository(self._current_uow.session)
        await repo.mark_processed(event_id)

    # ── Abstract: failure handling ────────────────────────────────────────────

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:  # type: ignore[type-arg]
        """Log the failure and return a dict record (no retry table needed)."""
        record = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        logger.warning("article_consumer_failure", **record)
        return record

    async def update_failure(self, failure: FailureInfo[dict]) -> None:  # type: ignore[type-arg]
        """No-op: retry tracking is handled via DLQ, not a separate table."""

    async def _dead_letter_impl(self, failure: FailureInfo[dict]) -> None:  # type: ignore[type-arg]
        """Write a DLQ row directly to dead_letter_queue via a new session."""
        import common.ids  # type: ignore[import-untyped]
        from content_store.infrastructure.db.models import DeadLetterQueueModel

        payload_json: dict[str, Any] = failure.record or {"event_id": failure.event_id}
        try:
            async with self._session_factory() as session:
                session.add(
                    DeadLetterQueueModel(
                        dlq_id=common.ids.new_uuid7(),
                        original_event_id=UUID(failure.event_id),
                        topic=failure.topic,
                        payload_json=payload_json,
                        error_detail=str(failure.last_error),
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("article_consumer_dlq_write_failed", event_id=failure.event_id)

    async def get_pending_retries(self) -> list[FailureInfo[dict]]:  # type: ignore[type-arg]
        """Return empty list — retries are handled by DLQ admin, not in-process."""
        return []

    async def process_message_from_failure(self, failure: FailureInfo[dict]) -> None:  # type: ignore[type-arg]
        """No-op: retries are handled by DLQ admin (manual requeue)."""

    # ── Abstract: UoW ─────────────────────────────────────────────────────────

    async def get_unit_of_work(self) -> _SessionUnitOfWork:
        """Create and store a fresh session-backed unit of work."""
        uow = _SessionUnitOfWork(self._session_factory)
        self._current_uow = uow
        return uow

    # ── Abstract: deserialization ─────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Avro-encoded bytes; fall back to JSON if schema unavailable."""
        if schema_path:
            try:
                return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
            except Exception:
                logger.debug("avro_deserialize_failed_falling_back_to_json", schema_path=schema_path)
        return cast("dict[str, Any]", json.loads(raw.decode()))

    def get_schema_path(self, topic: str) -> str | None:
        """Return the filesystem path to content.article.raw.v1.avsc."""
        path = _SCHEMA_DIR / f"{topic}.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        """Extract the idempotency event ID from the Avro envelope."""
        return str(value["event_id"])

    # ── Abstract: message processing ─────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Run the full S5 processing pipeline for a single article event.

        Delegates to ProcessArticleUseCase. Stores the summary on
        ``self._current_summary`` for post-commit LSH indexing in
        ``_handle_message`` (CR-3 compliance).

        Args:
            key: Kafka message key (unused).
            value: Deserialized content.article.raw.v1 Avro dict.
            headers: Kafka message headers (unused).
        """
        article = _parse_raw_event(value)
        uow = self._current_uow
        assert uow is not None and uow.session is not None

        use_case = ProcessArticleUseCase(
            document_repo=DocumentRepository(uow.session),
            dedup_repo=DedupHashRepository(uow.session),
            minhash_repo=MinHashRepository(uow.session),
            outbox_repo=OutboxRepository(uow.session),
            bronze_store=BronzeStorageAdapter(self._store, self._app_config.bronze_bucket),
            bronze_bucket=self._app_config.bronze_bucket,
            silver_storage=SilverStorageAdapter(self._store, self._app_config.silver_bucket),
            lsh_client=self._lsh,
            output_topic=self._app_config.output_topic,
            num_perm=self._app_config.num_perm,
        )
        # R24: pass pre-fetched bytes (fetched before session opened in _handle_message)
        # F-DP2-05 (PLAN-deep-qa-iter2): when the bronze object is missing, the use
        # case raises BronzeObjectNotFoundError after logging a structured warning.
        # We swallow it here and leave _current_summary as None so the base consumer
        # commits the offset (no retry, no DLQ traceback) — bronze corruption is
        # operational and retrying the same missing key won't help.
        try:
            self._current_summary = await use_case.execute(article, prefetched_bytes=self._prefetched_bytes)
        except BronzeObjectNotFoundError:
            self._current_summary = None
            return

    # ── CR-3: post-commit LSH indexing ────────────────────────────────────────

    async def _handle_message(self, msg: Any) -> None:
        """Override to add LSH indexing AFTER the DB commit (CR-3) and GC on failure.

        The base class handles: deserialise → is_duplicate → get_unit_of_work
        → process_message → mark_processed → uow.commit.

        After that succeeds we index into the Valkey LSH bands best-effort.
        On commit failure, delete any orphaned silver MinIO object best-effort.

        R24: bronze bytes are pre-fetched here, BEFORE super()._handle_message opens
        a DB session, to avoid holding a DB connection during external I/O.
        """
        self._current_summary = None
        self._current_uow = None  # reset so is_duplicate always uses a fresh session
        self._prefetched_bytes = None  # R24: reset; populated below before session opens
        _start = time.perf_counter()

        # R24: Pre-fetch bronze bytes BEFORE the DB session opens.
        # We deserialize the message here (the base class will deserialize again;
        # the overhead is negligible compared to avoiding a held DB conn during I/O).
        #
        # F-DP2-05 (PLAN-deep-qa-iter2): if prefetch fails because the bronze
        # object is missing (NoSuchKey / ObjectNotFoundError), short-circuit
        # message processing entirely instead of falling through to the in-session
        # fetch (which would just hit the same NoSuchKey and raise an unhandled
        # traceback).  We log a structured warning and return so the base consumer
        # commits the offset cleanly.
        try:
            raw = msg.value()
            schema_path = self.get_schema_path(msg.topic())
            value = self.deserialize_value(raw, schema_path)
            article = _parse_raw_event(value)
            self._prefetched_bytes = await self._store.get_bytes(
                self._app_config.bronze_bucket, article.minio_bronze_key
            )
            logger.debug("bronze_prefetched", key=article.minio_bronze_key)
        except Exception as exc:
            # Bucket / key missing — skip cleanly, don't even attempt in-session fallback.
            exc_name = type(exc).__name__
            if exc_name in {"ObjectNotFoundError", "NoSuchKey", "FileNotFoundError"}:
                logger.warning(
                    "bronze_object_missing_skipping",
                    bronze_key=getattr(locals().get("article"), "minio_bronze_key", None),
                    error=str(exc),
                )
                # Mark the message processed via the base consumer's normal flow
                # by deferring to it — but the use case will short-circuit again
                # on the same missing key inside process_message().  To avoid the
                # extra session, just return early here: the base run loop will
                # commit the next message's offset on its next poll.
                return
            logger.warning(
                "bronze_prefetch_failed_falling_back_to_in_session_fetch",
                error=str(exc),
            )
            # Fall through: use case will fetch bytes inside the DB session as fallback.

        try:
            await super()._handle_message(msg)  # type: ignore[misc]
        except Exception:
            # GC: if silver write succeeded but DB commit failed, delete orphaned object
            summary = self._current_summary
            if summary is not None and summary.minio_silver_key is not None:
                try:
                    await self._store.delete(self._app_config.silver_bucket, summary.minio_silver_key)
                    logger.info("silver_gc_success", silver_key=summary.minio_silver_key)
                except Exception:
                    logger.warning("silver_gc_failed", silver_key=summary.minio_silver_key)
            self._current_summary = None
            raise

        # ── Metrics recording (post-commit) ──────────────────────────────────
        # Record after the DB commit so only successfully committed articles
        # are counted. Suppressed articles are also counted here with their
        # outcome tier, giving a complete picture of the dedup pipeline.
        summary = self._current_summary
        if summary is not None:
            _duration = time.perf_counter() - _start
            record_processing_outcome(
                suppressed=summary.suppressed,
                dedup_result=str(summary.decision.outcome),
                duration=_duration,
            )

        # ── CR-3: LSH indexing AFTER commit ──────────────────────────────────
        if summary is not None and summary.signature is not None and summary.doc_id is not None:
            try:
                await self._lsh.index(
                    summary.doc_id,
                    summary.signature,
                    summary.source_type or "",
                    summary.source_type or "",
                )
            except Exception:
                s5_lsh_index_failures_total.inc()
                logger.error("lsh_index_failed", doc_id=str(summary.doc_id))
        self._current_summary = None
