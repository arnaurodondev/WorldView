"""Worker 13F: Relation summary embedding refresh (PRD §6.7 Block 13F).

Runs every 2 hours.  Finds current relation summaries that have
``summary_text IS NOT NULL`` but ``summary_embedding IS NULL``,
and computes embeddings via FallbackChainClient.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BATCH_LIMIT = 100
_DEFAULT_EMBED_MODEL_ID = "nomic-embed-text"


class EmbeddingRefreshWorker:
    """Embeds relation summaries that are missing embeddings (Worker 13F).

    Args:
        session_factory:   Read/write sessionmaker for intelligence_db.
        llm_client:        FallbackChainClient (embedding path).
        embedding_model_id: Model ID passed to EmbeddingInput (default: nomic-embed-text).
                           Set via KNOWLEDGE_GRAPH_EMBEDDING_MODEL_ID env var.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        embedding_model_id: str = _DEFAULT_EMBED_MODEL_ID,
    ) -> None:
        self._sf = session_factory
        self._llm = llm_client
        self._embed_model_id = embedding_model_id

    async def run(self) -> None:
        """Embed current relation summaries that lack embeddings."""
        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
            RelationSummaryRepository,
        )

        refreshed = 0
        async with self._sf() as session:
            rel_repo = RelationRepository(session)
            summary_repo = RelationSummaryRepository(session)

            rows = await rel_repo.fetch_stale_summary_embeddings(_BATCH_LIMIT)  # type: ignore[attr-defined]

            for row in rows:
                summary_id = row["summary_id"]  # type: ignore[assignment]
                summary_text = str(row["summary_text"])

                inp = EmbeddingInput(text=summary_text, model_id=self._embed_model_id)
                outputs = await self._llm.embed([inp])
                if outputs is None or not outputs:
                    continue

                await summary_repo.update_embedding(summary_id, outputs[0].embedding)  # type: ignore[arg-type, attr-defined]
                refreshed += 1

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "embedding_refresh_worker_complete",
            summaries_embedded=refreshed,
        )
