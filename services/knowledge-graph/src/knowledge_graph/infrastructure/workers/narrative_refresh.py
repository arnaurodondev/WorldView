"""Worker 13D-2: Narrative state embedding refresh (PRD §6.7 Block 13D-2).

Hourly check for entities WHERE view_type='narrative' AND next_refresh_at < now().

Source text (deterministic template — NO LLM):
  canonical_name + entity_type
  + top-5 claims by date
  + top-5 mention contexts (incl. light-tier)
  + active contradictions

Truncated to 512 tokens (approx. 2048 chars).
UPSERT with next_refresh_at = now() + 7 days.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    VIEW_NARRATIVE,
    sha256_hex,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_REFRESH_INTERVAL_DAYS = 7
_BATCH_LIMIT = 100
_EMBED_MODEL_ID = "nomic-embed-text"
_MAX_CHARS = 2048  # ~512 tokens


class NarrativeRefreshWorker:
    """Refreshes narrative-view embeddings (Worker 13D-2).

    No LLM — deterministic template → embedding only.

    Args:
        session_factory: Read/write sessionmaker for intelligence_db.
        llm_client:      FallbackChainClient (embedding path only).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
    ) -> None:
        self._sf = session_factory
        self._llm = llm_client

    async def run(self) -> None:
        """Refresh narrative embeddings due for refresh."""
        from datetime import timedelta

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        refreshed = 0
        async with self._sf() as session:
            emb_repo = EntityEmbeddingStateRepository(session)
            due = await emb_repo.get_due_for_refresh(VIEW_NARRATIVE, _BATCH_LIMIT)

            for row in due:
                entity_id: UUID = row["entity_id"]  # type: ignore[assignment]

                source_text = await self._build_narrative_text(
                    entity_id=entity_id,
                    canonical_name=str(row.get("canonical_name", "")),
                    entity_type=str(row.get("entity_type", "")),
                    session=session,
                )
                source_text = source_text[:_MAX_CHARS]
                source_hash = sha256_hex(source_text)

                from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

                inp = EmbeddingInput(text=source_text, model_id=_EMBED_MODEL_ID)
                outputs = await self._llm.embed([inp], entity_id=entity_id)
                embedding = outputs[0].embedding if outputs else None

                await emb_repo.upsert(
                    entity_id,
                    VIEW_NARRATIVE,
                    embedding=embedding,
                    model_id=_EMBED_MODEL_ID if embedding else None,
                    source_text=source_text,
                    source_hash=source_hash,
                    next_refresh_at=utc_now() + timedelta(days=_REFRESH_INTERVAL_DAYS),  # type: ignore[no-any-return, operator]
                )
                refreshed += 1

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "narrative_refresh_worker_complete",
            refreshed=refreshed,
        )

    async def _build_narrative_text(
        self,
        entity_id: UUID,
        canonical_name: str,
        entity_type: str,
        session: AsyncSession,
    ) -> str:
        """Build deterministic narrative text for an entity."""
        from sqlalchemy import text as sql_text

        parts = [f"{canonical_name} ({entity_type})"]

        # Top-5 claims by date
        claims_result = await session.execute(
            sql_text("""
SELECT claim_text FROM claims
WHERE subject_entity_id = :entity_id AND polarity != 'neutral'
ORDER BY created_at DESC LIMIT 5
"""),
            {"entity_id": str(entity_id)},
        )
        for row in claims_result.fetchall():
            parts.append(f"Claim: {row[0]}")

        # Active contradictions summary
        contra_result = await session.execute(
            sql_text("""
SELECT c1.claim_type, c1.polarity, c2.polarity
FROM relation_contradiction_links rcl
JOIN relation_evidence_raw rer ON rer.raw_id = rcl.relation_evidence_id
JOIN claims c1 ON c1.claim_id = rcl.claim_id
JOIN claims c2 ON c2.claim_id = rcl.claim_id
WHERE rer.subject_entity_id = :entity_id
  AND rcl.invalidated_at IS NULL
ORDER BY rcl.detected_at DESC LIMIT 3
"""),
            {"entity_id": str(entity_id)},
        )
        for row in contra_result.fetchall():
            parts.append(f"Contradiction on {row[0]}: {row[1]} vs {row[2]}")

        return "\n".join(parts)
