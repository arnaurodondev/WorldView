"""Document deletion consumer for the NLP Pipeline (S6).

Consumes ``content.document.deleted.v1`` events emitted by S4 when a tenant
deletes an uploaded document via the REST API.  For each deletion event the
consumer removes all NLP artifacts that were produced for that document:

    entity_mentions  →  sections  →  chunks

Delete order is important: entity_mentions may have FKs into chunks/sections,
and chunks may have FKs into chunk_embeddings (which cascade via FK on chunk_id
if the DB schema uses ON DELETE CASCADE on chunk_embeddings.chunk_id).  Deleting
in ``entity_mentions → sections → chunks`` order avoids FK violation errors.

Idempotency
-----------
DELETE statements are inherently idempotent — re-delivery of the same event
produces zero-row deletes on all three tables if they were already cleaned up
on the first delivery.  ``ValkeyDedupMixin`` provides a fast-path 24h dedup
window so that the DB is not touched on obvious re-deliveries.  The downstream
writes being idempotent means the at-least-once fallback (Valkey unavailable)
is safe.

PLAN-0086 Wave F-1 (T-F-1-01).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

import structlog
from sqlalchemy import text

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

# Avro schema path for content.document.deleted.v1 — used to deserialize
# Confluent-framed bytes produced by the S4 outbox dispatcher.
_DELETED_SCHEMA_PATH = get_schema_path("content.document.deleted.v1.avsc")

_TOPIC = "content.document.deleted.v1"


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


class DocumentDeletionConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    """Consumes content.document.deleted.v1 and purges NLP artifacts.

    Downstream writes (DELETE statements) are inherently idempotent —
    re-delivering the same event produces zero-row deletes, which is safe.
    The Valkey dedup window provides a fast-path skip for obvious re-deliveries
    within 24 hours.

    Tenant isolation: every DELETE is scoped to ``(doc_id, tenant_id)`` so a
    deletion event for tenant A never removes data belonging to tenant B.
    """

    # ── ValkeyDedupMixin class attributes ────────────────────────────────────
    # Unique prefix prevents key collisions with other consumers' dedup sets.
    _topic: ClassVar[str] = "content.document.deleted.v1"
    _consumer_group: ClassVar[str] = "s6-document-deletion"
    _dedup_prefix: str = "nlp:dd:dedup"
    _dedup_ttl_seconds: ClassVar[int] = 86400  # 24 hours — matches topic retention

    def __init__(
        self,
        config: ConsumerConfig,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        valkey_client: ValkeyClient | None = None,
    ) -> None:
        super().__init__(config)
        # ValkeyDedupMixin reads _dedup_client for dedup checks.
        self._dedup_client = valkey_client
        self._nlp_sf = nlp_session_factory

    # ── UoW (no-op — session managed directly inside process_message) ────────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        # The article consumer uses the same no-op pattern.  We open sessions
        # manually inside process_message so each deletion is atomic.
        return _NoOpUnitOfWork()  # type: ignore[return-value]

    # ── Core processing ───────────────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Delete NLP artifacts for a deleted tenant document.

        Delete order (entity_mentions → sections → chunks) ensures that FK
        constraints are never violated:
        - entity_mentions may reference sections/chunks via section_id / chunk_id
        - chunk_embeddings cascade-delete from chunks (FK ON DELETE CASCADE)

        Both doc_id and tenant_id predicates are applied on every statement to
        preserve per-tenant data isolation — a bug in S4 that emits the wrong
        tenant_id cannot affect another tenant's data here.
        """
        doc_id = UUID(str(value["doc_id"]))
        tenant_id = UUID(str(value["tenant_id"]))

        log.info(  # type: ignore[no-any-return]
            "document_deletion_received",
            doc_id=str(doc_id),
            tenant_id=str(tenant_id),
        )

        async with self._nlp_sf() as session:
            # Step 1: entity_mentions (references sections + chunks by FK)
            await session.execute(
                text("DELETE FROM entity_mentions WHERE doc_id = :doc_id AND tenant_id = :tid"),
                {"doc_id": doc_id, "tid": tenant_id},
            )
            # Step 2: sections (parent of chunks in the section_id hierarchy)
            await session.execute(
                text("DELETE FROM sections WHERE doc_id = :doc_id AND tenant_id = :tid"),
                {"doc_id": doc_id, "tid": tenant_id},
            )
            # Step 3: chunks — chunk_embeddings cascade via FK on chunk_id
            # (verified in migration 0019: chunk_embeddings.chunk_id → chunks.chunk_id
            # ON DELETE CASCADE).
            await session.execute(
                text("DELETE FROM chunks WHERE doc_id = :doc_id AND tenant_id = :tid"),
                {"doc_id": doc_id, "tid": tenant_id},
            )
            await session.commit()

        log.info(  # type: ignore[no-any-return]
            "document_deletion_complete",
            doc_id=str(doc_id),
            tenant_id=str(tenant_id),
        )

    # ── Failure tracking ──────────────────────────────────────────────────────

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        log.warning(  # type: ignore[no-any-return]
            "document_deletion_consumer_retry_skipped",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        log.error(  # type: ignore[no-any-return]
            "document_deletion_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        log.warning(  # type: ignore[no-any-return]
            "document_deletion_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        log.error(  # type: ignore[no-any-return]
            "document_deletion_consumer_dead_lettered",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Confluent-Avro or JSON payload.

        S4 dispatcher publishes content.document.deleted.v1 as Confluent Avro
        wire format (5-byte header: magic 0x00 + 4-byte schema ID).  Fall back
        to JSON for plain payloads (e.g. integration tests).
        """
        if raw and raw[0:1] == b"\x00":
            from messaging.kafka.serialization_utils import (  # type: ignore[import-untyped]
                deserialize_confluent_avro,
            )

            return deserialize_confluent_avro(_DELETED_SCHEMA_PATH, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _TOPIC:
            return _DELETED_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
