"""Document-ready consumer for Content Ingestion (S4).

Consumes ``nlp.document.ready.v1`` events emitted by S6 after all NLP artifacts
(chunks, embeddings, entity_mentions) have been successfully created for a
tenant-uploaded document.  For each event the consumer calls
``TenantDocumentUploadRepository.set_ready()`` to transition the upload row to
``status=ready`` and store the pipeline output counts (chunk_count, word_count).

This is the final step in the tenant-document processing lifecycle:

    S4 upload API → content.article.stored.v1 → S6 pipeline
                  → nlp.document.ready.v1      → S4 set_ready

Idempotency
-----------
``set_ready`` is implemented as a ``WHERE (doc_id, tenant_id)`` UPDATE — re-
delivering the same event simply overwrites the row with the same values, which
is safe.  ``ValkeyDedupMixin`` provides a fast-path 24h dedup window to skip
obvious re-deliveries without touching the DB.

PLAN-0086 Wave F-1 (T-F-1-02).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

import structlog

from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

log = structlog.get_logger()  # type: ignore[no-any-return]

# Avro schema path for nlp.document.ready.v1 — used to deserialize
# Confluent-framed bytes produced by the S6 outbox.
_READY_SCHEMA_PATH = get_schema_path("nlp.document.ready.v1.avsc")

_TOPIC = "nlp.document.ready.v1"


class _NoOpUnitOfWork:
    """Thin UoW stub — this consumer manages its own session inside process_message."""

    async def __aenter__(self) -> _NoOpUnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class DocumentReadyConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    """Consumes nlp.document.ready.v1 and marks uploads as READY.

    The ``set_ready`` UPDATE is idempotent — the same (doc_id, tenant_id,
    chunk_count, word_count) applied twice produces the same result.
    The Valkey dedup window avoids unnecessary DB round-trips on re-delivery.

    Dependencies
    ------------
    ``nlp_session_factory``  — async_sessionmaker for the S4 primary DB
    ``valkey_client``        — optional; None ⟹ at-least-once mode (safe)
    """

    # ── ValkeyDedupMixin class attributes ────────────────────────────────────
    _topic: ClassVar[str] = "nlp.document.ready.v1"
    _consumer_group: ClassVar[str] = "s4-document-ready"
    _dedup_prefix: str = "ci:dr:dedup"
    _dedup_ttl_seconds: ClassVar[int] = 86400  # 24 hours

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        valkey_client: ValkeyClient | None = None,
    ) -> None:
        super().__init__(config)
        # ValkeyDedupMixin reads _dedup_client for dedup checks.
        self._dedup_client = valkey_client
        # Session factory for the S4 content-ingestion database (primary replica
        # is required since set_ready performs a write UPDATE).
        self._sf = session_factory

    # ── UoW (no-op — session managed directly inside process_message) ────────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUnitOfWork()  # type: ignore[return-value]

    # ── Core processing ───────────────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Transition a tenant upload to READY and store pipeline output counts.

        Extracts (doc_id, tenant_id, chunk_count, word_count) from the event
        payload and calls set_ready().  Missing or unparseable fields cause the
        message to be dead-lettered (ValueError raised → RetryableError wrapping
        in BaseKafkaConsumer → DLQ after max_retries).
        """
        doc_id = UUID(str(value["doc_id"]))
        tenant_id = UUID(str(value["tenant_id"]))
        chunk_count = int(value["chunk_count"])
        word_count = int(value["word_count"])

        log.info(  # type: ignore[no-any-return]
            "document_ready_received",
            doc_id=str(doc_id),
            tenant_id=str(tenant_id),
            chunk_count=chunk_count,
            word_count=word_count,
        )

        async with self._sf() as session:
            from content_ingestion.infrastructure.db.repositories.tenant_upload import (
                TenantDocumentUploadRepository,
            )

            upload_repo = TenantDocumentUploadRepository(session)
            # set_ready is a WHERE (doc_id, tenant_id) UPDATE — safe to re-run.
            await upload_repo.set_ready(
                doc_id=doc_id,
                tenant_id=tenant_id,
                chunk_count=chunk_count,
                word_count=word_count,
            )
            await session.commit()

        log.info(  # type: ignore[no-any-return]
            "document_ready_complete",
            doc_id=str(doc_id),
            tenant_id=str(tenant_id),
            chunk_count=chunk_count,
            word_count=word_count,
        )

    # ── Failure tracking ──────────────────────────────────────────────────────

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        log.warning(  # type: ignore[no-any-return]
            "document_ready_consumer_retry_skipped",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        log.error(  # type: ignore[no-any-return]
            "document_ready_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        log.warning(  # type: ignore[no-any-return]
            "document_ready_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        log.error(  # type: ignore[no-any-return]
            "document_ready_consumer_dead_lettered",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Confluent-Avro or JSON payload.

        S6 outbox publishes nlp.document.ready.v1 as Confluent Avro wire format
        (5-byte header: magic 0x00 + 4-byte schema ID).  Fall back to JSON for
        plain payloads (e.g. integration tests).
        """
        if raw and raw[0:1] == b"\x00":
            from messaging.kafka.serialization_utils import (  # type: ignore[import-untyped]
                deserialize_confluent_avro,
            )

            return deserialize_confluent_avro(_READY_SCHEMA_PATH, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _TOPIC:
            return _READY_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
