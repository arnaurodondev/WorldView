"""Worker 13D-1: Definition embedding refresh (PRD §6.7 Block 13D-1).

Triggered indirectly via consumers (market.instrument.created, market.dataset.fetched)
and also runs as a periodic fallback (quarterly — 90-day schedule).

Change detection: SHA-256(source_text) != source_hash → re-embed.
Uses FallbackChainClient: Ollama → Gemini Flash Lite → NULL + schedule retry.
UPSERT entity_embedding_state WHERE view_type='definition' with
next_refresh_at = now() + 90 days.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    VIEW_DEFINITION,
    sha256_hex,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_REFRESH_INTERVAL_DAYS = 90
_BATCH_LIMIT = 50
_EMBED_MODEL_ID = "nomic-embed-text"


class DefinitionRefreshWorker:
    """Refreshes definition-view embeddings for entities (Worker 13D-1).

    Args:
        session_factory: Read/write sessionmaker for intelligence_db.
        llm_client:      FallbackChainClient (embedding path).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
    ) -> None:
        self._sf = session_factory
        self._llm = llm_client

    async def run(self) -> None:
        """Periodic fallback: refresh definition embeddings due for refresh."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        refreshed = 0
        skipped = 0
        async with self._sf() as session:
            emb_repo = EntityEmbeddingStateRepository(session)
            due = await emb_repo.get_due_for_refresh(VIEW_DEFINITION, _BATCH_LIMIT)

            for row in due:
                entity_id: UUID = row["entity_id"]  # type: ignore[assignment]
                source_text = str(row.get("source_text") or "")
                if not source_text:
                    continue

                new_hash = sha256_hex(source_text)
                if new_hash == row.get("source_hash"):
                    # Unchanged — just push next_refresh_at forward
                    await emb_repo.upsert(
                        entity_id,
                        VIEW_DEFINITION,
                        embedding=None,
                        model_id=None,
                        source_text=source_text,
                        source_hash=new_hash,
                        next_refresh_at=utc_now() + timedelta(days=_REFRESH_INTERVAL_DAYS),  # type: ignore[no-any-return, operator]
                    )
                    skipped += 1
                    continue

                embedding = await self._embed(entity_id, source_text)
                if embedding is None:
                    # Fallback exhausted; next_refresh_at stays unchanged → retry next cycle
                    continue

                await emb_repo.upsert(
                    entity_id,
                    VIEW_DEFINITION,
                    embedding=embedding,
                    model_id=_EMBED_MODEL_ID,
                    source_text=source_text,
                    source_hash=new_hash,
                    next_refresh_at=utc_now() + timedelta(days=_REFRESH_INTERVAL_DAYS),  # type: ignore[no-any-return, operator]
                )
                refreshed += 1

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "definition_refresh_worker_complete",
            refreshed=refreshed,
            skipped_unchanged=skipped,
        )

    async def refresh_for_entity(
        self,
        entity_id: UUID,
        source_text: str,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        """Refresh definition embedding for a specific entity (consumer-triggered).

        Uses the worker's own session factory if no override provided.
        Change detection: skip if SHA-256 matches stored hash.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        sf = session_factory or self._sf
        new_hash = sha256_hex(source_text)

        async with sf() as session:
            emb_repo = EntityEmbeddingStateRepository(session)
            existing = await emb_repo.get(entity_id, VIEW_DEFINITION)

            if existing and existing.get("source_hash") == new_hash:
                logger.debug(  # type: ignore[no-any-return]
                    "definition_refresh_skipped_unchanged",
                    entity_id=str(entity_id),
                )
                return

            embedding = await self._embed(entity_id, source_text)
            await emb_repo.upsert(
                entity_id,
                VIEW_DEFINITION,
                embedding=embedding,
                model_id=_EMBED_MODEL_ID if embedding else None,
                source_text=source_text,
                source_hash=new_hash,
                next_refresh_at=utc_now() + timedelta(days=_REFRESH_INTERVAL_DAYS),  # type: ignore[no-any-return, operator]
            )
            await session.commit()

    async def _embed(self, entity_id: UUID, text: str) -> list[float] | None:
        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

        inp = EmbeddingInput(text=text, model_id=_EMBED_MODEL_ID)
        outputs = await self._llm.embed([inp], entity_id=entity_id)
        if outputs is None or not outputs:
            return None
        return outputs[0].embedding
