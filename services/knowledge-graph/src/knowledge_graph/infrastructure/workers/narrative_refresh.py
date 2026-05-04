"""Worker 13D-2: Narrative state embedding refresh (PRD §6.7 Block 13D-2).

Hourly check for entities WHERE view_type='narrative' AND next_refresh_at < now().

Source text (deterministic template — NO LLM):
  canonical_name + entity_type
  + top-5 claims by date
  + top-5 mention contexts (incl. light-tier)
  + active contradictions

Truncated to 512 tokens (approx. 2048 chars).
UPSERT with next_refresh_at = now() + 7 days.

Performance (batch embed):
  Phase 1 — Read all due entities and build narrative texts (DB session, then close).
  Phase 2 — Call embed() ONCE with all texts (no session held).
  Phase 3 — Write all upserts in a single session + commit.
  This eliminates N round-trips to the embedding API (was one per entity).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    VIEW_NARRATIVE,
    sha256_hex,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_REFRESH_INTERVAL_DAYS = 7
_DEFAULT_EMBED_MODEL_ID = "nomic-embed-text"
_MAX_CHARS = 2048  # ~512 tokens

# Maximum texts to send in a single embed() call.  DeepInfra and most providers
# accept batches of several hundred inputs; 200 is a conservative safe ceiling.
_EMBED_CHUNK_SIZE = 200


class NarrativeRefreshWorker:
    """Refreshes narrative-view embeddings (Worker 13D-2).

    No LLM — deterministic template → embedding only.

    Args:
    ----
        session_factory:    Read/write sessionmaker for intelligence_db.
        llm_client:         FallbackChainClient (embedding path only).
        embedding_model_id: Model ID passed to EmbeddingInput (default: nomic-embed-text).
                            Set via KNOWLEDGE_GRAPH_EMBEDDING_MODEL_ID env var.
        batch_limit:        Maximum entities to process per cycle. 0 (default) means
                            all due entities (no cap).  Set via
                            KNOWLEDGE_GRAPH_WORKER_EMBEDDING_BATCH_LIMIT.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        embedding_model_id: str = _DEFAULT_EMBED_MODEL_ID,
        batch_limit: int = 0,
    ) -> None:
        self._sf = session_factory
        self._embed_model_id = embedding_model_id
        self._llm = llm_client
        self._batch_limit = batch_limit

    async def run(self) -> None:
        """Refresh narrative embeddings due for refresh.

        Execution is split into three phases to avoid holding a DB session
        open during external HTTP/LLM calls (ARCH-003/004 pattern):

        Phase 1 — Read: fetch all due entities, build narrative texts, close session.
        Phase 2 — Embed: call embed() ONCE with all texts (no session held).
        Phase 3 — Write: upsert all results in a single session + commit.
        """
        import dataclasses
        from datetime import timedelta

        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        # ── Phase 1: Read ────────────────────────────────────────────────────
        # Open a single session, build all narrative texts, then close.
        # _build_narrative_text issues SQL queries but does not write anything.
        @dataclasses.dataclass
        class _Prepared:
            entity_id: UUID
            source_text: str
            source_hash: str

        prepared: list[_Prepared] = []

        async with self._sf() as session:
            emb_repo = EntityEmbeddingStateRepository(session)
            due = await emb_repo.get_due_for_refresh(VIEW_NARRATIVE, self._batch_limit)

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

                prepared.append(_Prepared(entity_id=entity_id, source_text=source_text, source_hash=source_hash))
        # Session released — no DB connection held during embed() calls.

        if not prepared:
            logger.info(  # type: ignore[no-any-return]
                "narrative_refresh_worker_complete",
                refreshed=0,
            )
            return

        # ── Phase 2: Batch embed ─────────────────────────────────────────────
        # Build ONE list of all inputs and call embed() once (or in chunks of
        # _EMBED_CHUNK_SIZE when the entity count exceeds the API batch ceiling).
        all_embeddings: list[list[float] | None] = []

        inputs_all = [EmbeddingInput(text=p.source_text, model_id=self._embed_model_id) for p in prepared]

        # Chunk the inputs to stay within API batch limits.
        for chunk_start in range(0, len(inputs_all), _EMBED_CHUNK_SIZE):
            chunk_inputs = inputs_all[chunk_start : chunk_start + _EMBED_CHUNK_SIZE]
            outputs = await self._llm.embed(chunk_inputs)
            # Map outputs back by index; missing outputs (transient failure) → None.
            for i in range(len(chunk_inputs)):
                if outputs and i < len(outputs):
                    all_embeddings.append(outputs[i].embedding)
                else:
                    all_embeddings.append(None)

        # ── Phase 3: Write ───────────────────────────────────────────────────
        refreshed = 0
        async with self._sf() as session:
            emb_repo = EntityEmbeddingStateRepository(session)
            for p, embedding in zip(prepared, all_embeddings, strict=False):
                await emb_repo.upsert(
                    p.entity_id,
                    VIEW_NARRATIVE,
                    embedding=embedding,
                    model_id=self._embed_model_id if embedding is not None else None,
                    source_text=p.source_text,
                    source_hash=p.source_hash,
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
