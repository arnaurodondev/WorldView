"""Worker 13E: Provisional entity enrichment (PRD §6.7 Block 13E / §14.2).

Runs every 10 minutes.  Processes ``provisional_entity_queue`` rows with
``status='pending'``:
  1. Use ExtractionClient (FallbackChainClient) to generate entity profile
     (canonical_name, entity_type, ticker, ISIN).
  2. INSERT into canonical_entities.
  3. INSERT mechanical aliases (canonical_name, ticker, ISIN if available).
  4. INSERT 3 entity_embedding_state rows (definition + narrative + fundamentals).
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
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BATCH_LIMIT = 20
_EMBED_MODEL_ID = "nomic-embed-text"
_EXTRACT_MODEL_ID = "kg-entity-profile-v1"


class DirectProducerProtocol(Protocol):
    """Structural type for direct Kafka producer (entity.dirtied.v1)."""

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None: ...


class ProvisionalEnrichmentWorker:
    """Enriches provisional entities via LLM (Worker 13E).

    Args:
        session_factory:  Read/write sessionmaker for intelligence_db.
        llm_client:       FallbackChainClient for extraction + embedding.
        direct_producer:  Direct Kafka producer for entity.dirtied.v1.
        entity_dirtied_topic: Topic name for entity.dirtied.v1.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        direct_producer: DirectProducerProtocol | None = None,
        entity_dirtied_topic: str = "entity.dirtied.v1",
    ) -> None:
        self._sf = session_factory
        self._llm = llm_client
        self._producer = direct_producer
        self._dirtied_topic = entity_dirtied_topic

    async def run(self) -> None:
        """Enrich pending provisional entity queue entries."""
        from sqlalchemy import text

        enriched = 0
        failed = 0

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
                queue_id = UUID(str(row[0]))
                mention_text = str(row[1])
                mention_class = str(row[3])
                context_snippet = str(row[4]) if row[4] else ""

                try:
                    entity_id = await self._enrich_entity(
                        session=session,
                        queue_id=queue_id,
                        mention_text=mention_text,
                        mention_class=mention_class,
                        context_snippet=context_snippet,
                    )
                    if entity_id:
                        await session.execute(
                            text("""
UPDATE provisional_entity_queue
SET status = 'resolved', assigned_entity_id = :entity_id, resolved_at = now()
WHERE queue_id = :queue_id
"""),
                            {"entity_id": str(entity_id), "queue_id": str(queue_id)},
                        )
                        enriched += 1
                    else:
                        # LLM failed; increment retry_count
                        await session.execute(
                            text("""
UPDATE provisional_entity_queue
SET retry_count = retry_count + 1
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
                    failed += 1

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "provisional_enrichment_worker_complete",
            enriched=enriched,
            failed=failed,
        )

    async def _enrich_entity(
        self,
        session: AsyncSession,
        queue_id: UUID,
        mention_text: str,
        mention_class: str,
        context_snippet: str,
    ) -> UUID | None:
        """Extract entity profile via LLM and persist to intelligence_db."""
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

        # ---- Step 1: LLM extraction ----
        profile = await self._extract_entity_profile(mention_text, mention_class, context_snippet)
        if profile is None:
            return None

        canonical_name: str = profile.get("canonical_name") or mention_text
        entity_type: str = profile.get("entity_type") or mention_class
        ticker: str | None = profile.get("ticker")
        isin: str | None = profile.get("isin")

        # ---- Step 2: Create canonical entity ----
        entity_repo = CanonicalEntityRepository(session)
        entity_id = await entity_repo.create(  # type: ignore[attr-defined]
            canonical_name=canonical_name,
            entity_type=entity_type,
            ticker=ticker,
            isin=isin,
        )

        # ---- Step 3: Insert mechanical aliases ----
        alias_repo = EntityAliasRepository(session)
        normalized_name = canonical_name.lower().strip()
        await alias_repo.insert(entity_id, canonical_name, normalized_name, "EXACT", "provisional_enrichment")

        if ticker:
            await alias_repo.insert(entity_id, ticker, ticker.upper(), "TICKER", "provisional_enrichment")
        if isin:
            await alias_repo.insert(entity_id, isin, isin.upper(), "ISIN", "provisional_enrichment")

        # ---- Step 4: LLM-generated supplementary aliases (with collision check) ----
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

        # ---- Step 5: Ensure 3 entity_embedding_state rows ----
        emb_repo = EntityEmbeddingStateRepository(session)
        await emb_repo.ensure_rows_exist(entity_id)

        # ---- Step 6: Embed definition ----
        if canonical_name:
            await self._embed_definition(entity_id, canonical_name, emb_repo)

        # ---- Step 7: Unblock relation_evidence_raw rows ----
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

        # ---- Step 8: Emit entity.canonical.created.v1 via outbox ----
        outbox_repo = OutboxRepository(session)
        import json

        payload = json.dumps(
            {
                "event_id": str(new_uuid7()),
                "entity_id": str(entity_id),
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "provisional_queue_id": str(queue_id),
            }
        ).encode()

        await outbox_repo.append(
            topic="entity.canonical.created.v1",
            partition_key=str(entity_id),
            payload_avro=payload,
        )

        # ---- Step 9: entity.dirtied.v1 direct produce ----
        if self._producer:
            self._producer.produce_bytes(
                topic=self._dirtied_topic,
                key=str(entity_id).encode(),
                value=json.dumps({"entity_id": str(entity_id)}).encode(),
            )

        return entity_id  # type: ignore[no-any-return]

    async def _extract_entity_profile(
        self,
        mention_text: str,
        mention_class: str,
        context_snippet: str,
    ) -> dict[str, Any] | None:
        from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-untyped]

        inp = ExtractionInput(
            prompt=(
                f"Extract a canonical entity profile for '{mention_text}' "
                f"(type: {mention_class}). "
                "Return JSON with: canonical_name, entity_type, ticker (if applicable), "
                "isin (if applicable), aliases (list of common names)."
            ),
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

    async def _embed_definition(
        self,
        entity_id: UUID,
        source_text: str,
        emb_repo: EntityEmbeddingStateRepository,
    ) -> None:
        from datetime import timedelta

        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            VIEW_DEFINITION,
            sha256_hex,
        )

        inp = EmbeddingInput(text=source_text, model_id=_EMBED_MODEL_ID)
        outputs = await self._llm.embed([inp], entity_id=entity_id)
        embedding = outputs[0].embedding if outputs else None

        await emb_repo.upsert(
            entity_id,
            VIEW_DEFINITION,
            embedding=embedding,
            model_id=_EMBED_MODEL_ID if embedding else None,
            source_text=source_text,
            source_hash=sha256_hex(source_text),
            next_refresh_at=utc_now() + timedelta(days=90),  # type: ignore[no-any-return, operator]
        )
