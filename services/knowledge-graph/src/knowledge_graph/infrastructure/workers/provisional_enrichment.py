"""Worker 13E: Provisional entity enrichment (PRD §6.7 Block 13E / §14.2).

Runs every 10 minutes.  Processes ``provisional_entity_queue`` rows with
``status='pending'``:
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
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    EntityEmbeddingStateRepository,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BATCH_LIMIT = 20
_DEFAULT_EMBED_MODEL_ID = "nomic-embed-text"
_EXTRACT_MODEL_ID = "kg-entity-profile-v1"


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

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        direct_producer: DirectProducerProtocol | None = None,
        entity_dirtied_topic: str = "entity.dirtied.v1",
        embedding_model_id: str = _DEFAULT_EMBED_MODEL_ID,
        usage_logger: LlmUsageLogProtocol | None = None,
    ) -> None:
        self._sf = session_factory
        self._embed_model_id = embedding_model_id
        self._llm = llm_client
        self._producer = direct_producer
        self._dirtied_topic = entity_dirtied_topic
        # PLAN-0057 A-5 / F-CRIT-03: optional cost logger.  In practice the
        # FallbackChainClient already calls ``usage_logger.log()`` on every
        # embed/extract attempt — this attribute exists so call-site code can
        # write *additional* per-worker rows when needed and so injection-time
        # tests can assert the logger was threaded through ``build_workers``.
        self._usage_logger = usage_logger

    async def run(self) -> None:
        """Enrich pending provisional entity queue entries.

        ARCH-003 fix: read→release→I/O→acquire→write pattern.
        Session is NOT held open during external LLM / embedding HTTP calls.
        """
        from sqlalchemy import text

        enriched = 0
        failed = 0

        # Accumulate entity_ids that need entity.dirtied.v1 — produced AFTER commit
        # to avoid orphaned Kafka messages when the DB transaction fails.
        entity_ids_to_dirty: list[UUID] = []

        # ── Phase 1: Read pending rows, then release the session ──
        pending_rows: list[tuple[UUID, str, str, str]] = []
        async with self._sf() as session:
            result = await session.execute(
                text("""
SELECT queue_id, mention_text, normalized_surface, mention_class,
       context_snippet, source_doc_id
FROM provisional_entity_queue
WHERE status = 'pending'
ORDER BY created_at
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""),
                {"limit": _BATCH_LIMIT},
            )
            rows = result.fetchall()

            for row in rows:
                pending_rows.append(
                    (
                        UUID(str(row[0])),  # queue_id
                        str(row[1]),  # mention_text
                        str(row[3]),  # mention_class
                        str(row[4]) if row[4] else "",  # context_snippet
                    ),
                )

            # Mark rows as 'processing' to prevent other workers from picking them
            # up after we release the FOR UPDATE lock.  This is safe because the
            # lock is still held until commit.
            for queue_id, _, _, _ in pending_rows:
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
        # Each entry produces either an enrichment result or None (failure).
        # Both the LLM profile extraction AND the embedding HTTP call happen here,
        # completely outside any DB session (ARCH-003).
        enrichment_results: list[tuple[UUID, str, str, str, dict[str, Any] | None, list[float] | None]] = []
        for queue_id, mention_text, mention_class, context_snippet in pending_rows:
            try:
                profile = await self._extract_entity_profile(mention_text, mention_class, context_snippet)
                # Pre-compute embedding while we have no session open
                embedding: list[float] | None = None
                if profile is not None:
                    canonical_name = profile.get("canonical_name") or mention_text
                    if canonical_name:
                        embedding = await self._compute_embedding(None, canonical_name)
                enrichment_results.append((queue_id, mention_text, mention_class, context_snippet, profile, embedding))
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "provisional_enrichment_error",
                    queue_id=str(queue_id),
                    error=str(exc),
                )
                enrichment_results.append((queue_id, mention_text, mention_class, context_snippet, None, None))

        # ── Phase 3: Write results in a new session ──
        async with self._sf() as session:
            for queue_id, mention_text, _mention_class, _context_snippet, profile, embedding in enrichment_results:
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
                        await session.execute(
                            text("""
UPDATE provisional_entity_queue
SET status = 'resolved', assigned_entity_id = :entity_id, resolved_at = now()
WHERE queue_id = :queue_id
"""),
                            {"entity_id": str(entity_id), "queue_id": str(queue_id)},
                        )
                        entity_ids_to_dirty.append(entity_id)
                        enriched += 1
                    else:
                        # LLM failed; increment retry_count and reset status
                        await session.execute(
                            text("""
UPDATE provisional_entity_queue
SET retry_count = retry_count + 1, status = 'pending'
WHERE queue_id = :queue_id
"""),
                            {"queue_id": str(queue_id)},
                        )
                        failed += 1
                except Exception as exc:
                    logger.error(  # type: ignore[no-any-return]
                        "provisional_enrichment_error",
                        queue_id=str(queue_id),
                        error=str(exc),
                    )
                    # Reset to pending so the row is retried on the next cycle
                    await session.execute(
                        text("""
UPDATE provisional_entity_queue
SET retry_count = retry_count + 1, status = 'pending'
WHERE queue_id = :queue_id
"""),
                        {"queue_id": str(queue_id)},
                    )
                    failed += 1

            await session.commit()

        # Produce entity.dirtied.v1 AFTER successful DB commit to guarantee
        # no orphaned Kafka messages if the transaction rolled back.
        import json

        for dirty_id in entity_ids_to_dirty:
            if self._producer:
                self._producer.produce_bytes(
                    topic=self._dirtied_topic,
                    key=str(dirty_id).encode(),
                    value=json.dumps({"entity_id": str(dirty_id)}).encode(),
                )

        logger.info(  # type: ignore[no-any-return]
            "provisional_enrichment_worker_complete",
            enriched=enriched,
            failed=failed,
        )

    async def _persist_enrichment(
        self,
        session: AsyncSession,
        queue_id: UUID,
        mention_text: str,
        profile: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> UUID | None:
        """Persist an LLM-extracted entity profile to intelligence_db.

        This method only performs DB writes — no external HTTP/LLM calls.
        The LLM extraction and embedding HTTP calls are done in Phase 2,
        completely outside any DB session (ARCH-003 fix).
        """
        from sqlalchemy import text

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
            EntityAliasRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import (
            OutboxRepository,
        )

        canonical_name: str = profile.get("canonical_name") or mention_text
        entity_type: str = profile.get("entity_type") or str(profile.get("mention_class", "unknown"))
        ticker: str | None = profile.get("ticker")
        isin: str | None = profile.get("isin")

        # ---- Step 1: Create canonical entity ----
        entity_repo = CanonicalEntityRepository(session)
        entity_id = await entity_repo.create(  # type: ignore[attr-defined]
            canonical_name=canonical_name,
            entity_type=entity_type,
            ticker=ticker,
            isin=isin,
        )

        # ---- Step 2: Insert mechanical aliases ----
        alias_repo = EntityAliasRepository(session)
        normalized_name = canonical_name.lower().strip()
        await alias_repo.insert(entity_id, canonical_name, normalized_name, "EXACT", "provisional_enrichment")

        if ticker:
            await alias_repo.insert(entity_id, ticker, ticker.upper(), "TICKER", "provisional_enrichment")
        if isin:
            await alias_repo.insert(entity_id, isin, isin.upper(), "ISIN", "provisional_enrichment")

        # ---- Step 3: LLM-generated supplementary aliases (with collision check) ----
        llm_aliases: list[str] = profile.get("aliases") or []
        for alias in llm_aliases[:5]:  # Cap at 5 LLM aliases
            normalized = alias.lower().strip()
            existing = await alias_repo.find_exact(normalized)
            if existing and existing["entity_id"] != entity_id:
                logger.warning(  # type: ignore[no-any-return]
                    "provisional_enrichment_alias_collision",
                    alias=alias,
                    existing_entity_id=str(existing["entity_id"]),
                    new_entity_id=str(entity_id),
                )
                continue  # Reject — collision with different entity
            await alias_repo.insert(entity_id, alias, normalized, "LLM", "provisional_enrichment")

        # ---- Step 4: Ensure entity_embedding_state rows (2 for non-company, 3 for financial_instrument) ----
        emb_repo = EntityEmbeddingStateRepository(session)
        await emb_repo.ensure_rows_exist(entity_id, entity_type)

        # ---- Step 5: Write pre-computed embedding (computed in Phase 2, outside session) ----
        if canonical_name and embedding is not None:
            await self._write_embedding(entity_id, canonical_name, embedding, emb_repo)

        # ---- Step 6: Unblock relation_evidence_raw rows ----
        await session.execute(
            text("""
UPDATE relation_evidence_raw
SET entity_provisional = false,
    subject_entity_id  = :entity_id
WHERE provisional_queue_id = :queue_id
  AND entity_provisional   = true
"""),
            {"entity_id": str(entity_id), "queue_id": str(queue_id)},
        )

        # ---- Step 7: Emit entity.canonical.created.v1 via outbox ----
        outbox_repo = OutboxRepository(session)
        import json

        payload = json.dumps(
            {
                "event_id": str(new_uuid7()),
                "entity_id": str(entity_id),
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "provisional_queue_id": str(queue_id),
            },
        ).encode()

        await outbox_repo.append(
            topic="entity.canonical.created.v1",
            partition_key=str(entity_id),
            payload_avro=payload,
        )

        return entity_id  # type: ignore[no-any-return]

    async def _extract_entity_profile(
        self,
        mention_text: str,
        mention_class: str,
        context_snippet: str,
    ) -> dict[str, Any] | None:
        from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-untyped]
        from prompts.knowledge.entity_profile import ENTITY_PROFILE  # type: ignore[import-untyped]

        inp = ExtractionInput(
            prompt=ENTITY_PROFILE.render(name=mention_text, entity_class=mention_class),
            context=context_snippet,
            output_schema={
                "canonical_name": "string",
                "entity_type": "string",
                "ticker": "string|null",
                "isin": "string|null",
                "aliases": "list[string]",
            },
            model_id=_EXTRACT_MODEL_ID,
        )
        result = await self._llm.extract(inp, entity_id=None)
        if result is None:
            return None
        return result.result  # type: ignore[return-value]

    async def _compute_embedding(
        self,
        entity_id: UUID | None,
        source_text: str,
    ) -> list[float] | None:
        """Compute definition embedding via LLM HTTP call (no session needed).

        Called in Phase 2 outside any DB session to avoid holding connections
        during external I/O (ARCH-003).
        """
        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

        inp = EmbeddingInput(text=source_text, model_id=self._embed_model_id)
        outputs = await self._llm.embed([inp], entity_id=entity_id)
        return outputs[0].embedding if outputs else None

    async def _write_embedding(
        self,
        entity_id: UUID,
        source_text: str,
        embedding: list[float] | None,
        emb_repo: EntityEmbeddingStateRepository,
    ) -> None:
        """Write a pre-computed embedding to the DB (session-only, no HTTP)."""
        from datetime import timedelta

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            VIEW_DEFINITION,
            sha256_hex,
        )

        await emb_repo.upsert(
            entity_id,
            VIEW_DEFINITION,
            embedding=embedding,
            model_id=self._embed_model_id if embedding else None,
            source_text=source_text,
            source_hash=sha256_hex(source_text),
            next_refresh_at=utc_now() + timedelta(days=90),  # type: ignore[no-any-return, operator]
        )
