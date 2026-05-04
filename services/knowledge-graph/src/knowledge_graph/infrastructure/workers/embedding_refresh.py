"""Worker 13F: Relation summary embedding refresh (PRD §6.7 Block 13F).

Runs every 2 hours.  Finds current relation summaries that have
``summary_text IS NOT NULL`` but ``summary_embedding IS NULL``,
and computes embeddings via FallbackChainClient.

Performance (batch embed):
  Phase 1 — Read all stale summaries (DB session, then close).
  Phase 2 — Call embed() ONCE with all texts (no session held).
  Phase 3 — Write all updated embeddings in a single session + commit.
  This eliminates N round-trips to the embedding API (was one per summary).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_DEFAULT_EMBED_MODEL_ID = "nomic-embed-text"

# Maximum texts to send in a single embed() call.  DeepInfra and most providers
# accept batches of several hundred inputs; 200 is a conservative safe ceiling.
_EMBED_CHUNK_SIZE = 200


class EmbeddingRefreshWorker:
    """Embeds relation summaries that are missing embeddings (Worker 13F).

    Args:
    ----
        session_factory:    Read/write sessionmaker for intelligence_db.
        llm_client:         FallbackChainClient (embedding path).
        embedding_model_id: Model ID passed to EmbeddingInput (default: nomic-embed-text).
                            Set via KNOWLEDGE_GRAPH_EMBEDDING_MODEL_ID env var.
        batch_limit:        Maximum summaries to process per cycle. 0 (default) means
                            all stale summaries.  Set via
                            KNOWLEDGE_GRAPH_WORKER_EMBEDDING_BATCH_LIMIT.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        llm_client: FallbackChainClient,
        embedding_model_id: str = _DEFAULT_EMBED_MODEL_ID,
        batch_limit: int = 0,
    ) -> None:
        self._sf = session_factory
        self._llm = llm_client
        self._embed_model_id = embedding_model_id
        self._batch_limit = batch_limit

    async def run(self) -> None:
        """Embed current relation summaries that lack embeddings.

        Execution is split into three phases to avoid holding a DB session
        open during external LLM calls (ARCH-003/004 pattern):

        Phase 1 — Read: fetch all stale summaries, close session.
        Phase 2 — Embed: call embed() ONCE with all texts (no session held).
        Phase 3 — Write: update all embeddings in a single session + commit.
        """
        import dataclasses

        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
            RelationSummaryRepository,
        )

        # ── Phase 1: Read ────────────────────────────────────────────────────
        @dataclasses.dataclass
        class _Row:
            summary_id: UUID
            summary_text: str

        rows_to_embed: list[_Row] = []

        async with self._sf() as session:
            rel_repo = RelationRepository(session)
            raw_rows = await rel_repo.fetch_stale_summary_embeddings(self._batch_limit)  # type: ignore[attr-defined]
            for row in raw_rows:
                rows_to_embed.append(
                    _Row(
                        summary_id=row["summary_id"],  # type: ignore[arg-type]
                        summary_text=str(row["summary_text"]),
                    )
                )
        # Session released — no DB connection held during embed() calls.

        if not rows_to_embed:
            logger.info(  # type: ignore[no-any-return]
                "embedding_refresh_worker_complete",
                summaries_embedded=0,
            )
            return

        # ── Phase 2: Batch embed ─────────────────────────────────────────────
        # Build ONE list of all inputs and call embed() once (or in chunks of
        # _EMBED_CHUNK_SIZE when the summary count exceeds the API batch ceiling).
        all_embeddings: list[list[float] | None] = []

        inputs_all = [EmbeddingInput(text=r.summary_text, model_id=self._embed_model_id) for r in rows_to_embed]

        for chunk_start in range(0, len(inputs_all), _EMBED_CHUNK_SIZE):
            chunk_inputs = inputs_all[chunk_start : chunk_start + _EMBED_CHUNK_SIZE]
            outputs = await self._llm.embed(chunk_inputs)
            for i in range(len(chunk_inputs)):
                if outputs and i < len(outputs):
                    all_embeddings.append(outputs[i].embedding)
                else:
                    all_embeddings.append(None)

        # ── Phase 3: Write ───────────────────────────────────────────────────
        refreshed = 0
        async with self._sf() as session:
            summary_repo = RelationSummaryRepository(session)
            for _row_item, embedding in zip(rows_to_embed, all_embeddings, strict=False):
                if embedding is None:
                    # Transient embed failure — skip this summary; will retry next cycle.
                    continue
                await summary_repo.update_embedding(_row_item.summary_id, embedding)  # type: ignore[arg-type, attr-defined]
                refreshed += 1
            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "embedding_refresh_worker_complete",
            summaries_embedded=refreshed,
        )
