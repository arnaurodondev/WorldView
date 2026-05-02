"""Worker 13E: Provisional entity enrichment (PRD §6.7 Block 13E / §14.2).

Runs every 5 minutes (catch-up sweep). Hot path handled by
ProvisionalQueuedConsumer which reacts to entity.provisional.queued.v1 events
emitted by S6 UnresolvedResolutionWorker (PLAN-0061 Wave E).

Processes ``provisional_entity_queue`` rows with ``status='pending'``:
  1. Use ExtractionClient (FallbackChainClient) to generate entity profile
     (canonical_name, entity_type, ticker, ISIN).
  2. INSERT into canonical_entities.
  3. INSERT mechanical aliases (canonical_name, ticker, ISIN if available).
  4. INSERT 2-3 entity_embedding_state rows (financial_instrument: 3; others: 2).
  5. UPDATE provisional_entity_queue.status → 'resolved'.
  6. UPDATE relation_evidence_raw to clear entity_provisional flag.
  7. EMIT entity.canonical.created.v1 via outbox.
  8. EMIT entity.dirtied.v1 via direct Kafka produce.
  9. Log to llm_usage_log.

LLM alias collision validation: reject an LLM-generated alias if it maps
to a different entity in entity_aliases.

Shared enrichment logic lives in provisional_enrichment_core.py so the
hot-path ProvisionalQueuedConsumer can reuse the same LLM + DB steps.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from knowledge_graph.infrastructure.metrics.prometheus import (
    s7_provisional_enrichment_failed_total,
    s7_provisional_enrichment_success_total,
)
from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_DEFAULT_EMBED_MODEL_ID = "nomic-embed-text"


class DirectProducerProtocol(Protocol):
    """Structural type for direct Kafka producer (entity.dirtied.v1)."""

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None: ...


class ProvisionalEnrichmentWorker:
    """Enriches provisional entities via LLM (Worker 13E).

    Args:
    ----
        session_factory:   Read/write sessionmaker for intelligence_db.
        llm_client:        FallbackChainClient for extraction + embedding.
        direct_producer:   Direct Kafka producer for entity.dirtied.v1.
        entity_dirtied_topic: Topic name for entity.dirtied.v1.
        embedding_model_id: Model ID passed to EmbeddingInput (default: nomic-embed-text).
                           Set via KNOWLEDGE_GRAPH_EMBEDDING_MODEL_ID env var.
        batch_limit:       Max rows fetched per cycle (default 50). PLAN-0061 T-A-4.
        max_retries:       Rows exceeding this failure count become 'failed' (terminal).
                           PLAN-0061 T-A-3.
        concurrency:       Max concurrent LLM calls in Phase 2. PLAN-0061 T-A-4.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        direct_producer: DirectProducerProtocol | None = None,
        entity_dirtied_topic: str = "entity.dirtied.v1",
        embedding_model_id: str = _DEFAULT_EMBED_MODEL_ID,
        usage_logger: LlmUsageLogProtocol | None = None,
        batch_limit: int = 50,
        max_retries: int = 5,
        concurrency: int = 5,
    ) -> None:
        self._sf = session_factory
        self._embed_model_id = embedding_model_id
        self._llm = llm_client
        self._producer = direct_producer
        self._dirtied_topic = entity_dirtied_topic
        if direct_producer is None:
            logger.warning(  # type: ignore[no-any-return]
                "provisional_enrichment_worker_no_producer",
                message="direct_producer is None — entity.dirtied.v1 will not be emitted after enrichment",
            )
        # PLAN-0057 A-5 / F-CRIT-03: optional cost logger.  In practice the
        # FallbackChainClient already calls ``usage_logger.log()`` on every
        # embed/extract attempt — this attribute exists so call-site code can
        # write *additional* per-worker rows when needed and so injection-time
        # tests can assert the logger was threaded through ``build_workers``.
        self._usage_logger = usage_logger
        self._batch_limit = batch_limit
        self._max_retries = max_retries
        self._concurrency = concurrency

    async def run(self) -> None:
        """Enrich pending provisional entity queue entries.

        ARCH-003 fix: read→release→I/O→acquire→write pattern.
        Session is NOT held open during external LLM / embedding HTTP calls.
        """
        from sqlalchemy import text

        enriched = 0
        failed = 0

        entity_ids_to_dirty: list[UUID] = []

        # ── Phase 1: Read pending rows, then release the session ──
        pending_rows: list[tuple[UUID, str, str, str, int]] = []
        async with self._sf() as session:
            result = await session.execute(
                text("""
SELECT queue_id, mention_text, normalized_surface, mention_class,
       context_snippet, source_doc_id, retry_count
FROM provisional_entity_queue
WHERE status = 'pending'
  AND retry_count < :max_retries
ORDER BY created_at
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""),
                {"limit": self._batch_limit, "max_retries": self._max_retries},
            )
            rows = result.fetchall()

            for row in rows:
                pending_rows.append(
                    (
                        UUID(str(row[0])),  # queue_id
                        str(row[1]),  # mention_text
                        str(row[3]),  # mention_class
                        str(row[4]) if row[4] else "",  # context_snippet
                        int(row[6]) if row[6] is not None else 0,  # retry_count
                    ),
                )

            for queue_id, _, _, _, _ in pending_rows:
                await session.execute(
                    text("""
UPDATE provisional_entity_queue
SET status = 'processing'
WHERE queue_id = :queue_id
"""),
                    {"queue_id": str(queue_id)},
                )
            await session.commit()
        # Session released — no DB connection held during LLM calls.

        # ── Phase 2: LLM extraction + embedding (no session held) ──
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _enrich_one(
            row: tuple[UUID, str, str, str, int],
        ) -> tuple[UUID, str, str, str, int, dict[str, Any] | None, list[float] | None]:
            queue_id, mention_text, mention_class, context_snippet, retry_count = row
            async with semaphore:
                try:
                    profile = await self._extract_entity_profile(mention_text, mention_class, context_snippet)
                    embedding: list[float] | None = None
                    if profile is not None:
                        canonical_name = profile.get("canonical_name") or mention_text
                        if canonical_name:
                            embedding = await self._compute_embedding(None, canonical_name)
                    return (queue_id, mention_text, mention_class, context_snippet, retry_count, profile, embedding)
                except Exception as exc:
                    logger.error(  # type: ignore[no-any-return]
                        "provisional_enrichment_error",
                        queue_id=str(queue_id),
                        error=str(exc),
                    )
                    return (queue_id, mention_text, mention_class, context_snippet, retry_count, None, None)

        enrichment_results: list[tuple[UUID, str, str, str, int, dict[str, Any] | None, list[float] | None]] = list(
            await asyncio.gather(*[_enrich_one(r) for r in pending_rows])
        )

        # ── Phase 3: Write results in a new session ──
        async with self._sf() as session:
            for (
                queue_id,
                mention_text,
                _mention_class,
                _context_snippet,
                retry_count,
                profile,
                embedding,
            ) in enrichment_results:
                try:
                    if profile is not None:
                        entity_id = await self._persist_enrichment(
                            session=session,
                            queue_id=queue_id,
                            mention_text=mention_text,
                            profile=profile,
                            embedding=embedding,
                        )
                    else:
                        entity_id = None

                    if entity_id:
                        from sqlalchemy import text as sa_text

                        await session.execute(
                            sa_text("""
UPDATE provisional_entity_queue
SET status = 'resolved', assigned_entity_id = :entity_id, resolved_at = now()
WHERE queue_id = :queue_id
"""),
                            {"entity_id": str(entity_id), "queue_id": str(queue_id)},
                        )
                        entity_ids_to_dirty.append(entity_id)
                        s7_provisional_enrichment_success_total.inc()
                        enriched += 1
                    else:
                        await self._apply_retry(session, queue_id, retry_count)
                        failed += 1
                except Exception as exc:
                    logger.error(  # type: ignore[no-any-return]
                        "provisional_enrichment_error",
                        queue_id=str(queue_id),
                        error=str(exc),
                    )
                    await self._apply_retry(session, queue_id, retry_count)
                    failed += 1

            await session.commit()

        # Produce entity.dirtied.v1 AFTER successful DB commit.
        import json

        for dirty_id in entity_ids_to_dirty:
            if self._producer:
                try:
                    self._producer.produce_bytes(
                        topic=self._dirtied_topic,
                        key=str(dirty_id).encode(),
                        value=json.dumps({"entity_id": str(dirty_id)}).encode(),
                    )
                except Exception:
                    logger.warning(  # type: ignore[no-any-return]
                        "provisional_enrichment_dirtied_emit_failed",
                        entity_id=str(dirty_id),
                        exc_info=True,
                    )

        logger.info(  # type: ignore[no-any-return]
            "provisional_enrichment_worker_complete",
            enriched=enriched,
            failed=failed,
        )

    async def _apply_retry(
        self,
        session: Any,
        queue_id: UUID,
        retry_count: int,
    ) -> None:
        """Increment retry_count; transition to 'failed' when max_retries is reached.

        Delegates SQL to core.apply_retry_transition; increments the Prometheus
        counter here so test patch paths (which mock this module's counter) remain
        unchanged.
        """
        transitioned_to_failed = await core.apply_retry_transition(session, queue_id, retry_count, self._max_retries)
        if transitioned_to_failed:
            s7_provisional_enrichment_failed_total.inc()

    async def _persist_enrichment(
        self,
        session: AsyncSession,
        queue_id: UUID,
        mention_text: str,
        profile: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> UUID | None:
        """Delegate to core.persist_enrichment (session-only, no HTTP calls)."""
        return await core.persist_enrichment(
            session=session,
            queue_id=queue_id,
            mention_text=mention_text,
            profile=profile,
            embedding=embedding,
            embed_model_id=self._embed_model_id,
        )

    async def _extract_entity_profile(
        self,
        mention_text: str,
        mention_class: str,
        context_snippet: str,
    ) -> dict[str, Any] | None:
        """Delegate to core.extract_entity_profile."""
        return await core.extract_entity_profile(self._llm, mention_text, mention_class, context_snippet)

    async def _compute_embedding(
        self,
        entity_id: UUID | None,
        source_text: str,
    ) -> list[float] | None:
        """Delegate to core.compute_embedding."""
        return await core.compute_embedding(self._llm, entity_id, source_text, self._embed_model_id)
