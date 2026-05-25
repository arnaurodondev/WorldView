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

Also in this module: NarrativeRefreshKafkaConsumer (PLAN-0074 T-C-05).
  Kafka hot-path consumer for entity.narrative.generated.v1 events.  Triggers
  immediate narrative embedding refresh when a new LLM narrative is generated,
  without waiting for the next hourly NarrativeRefreshWorker cycle.
  The two classes are co-located because they share the same purpose (narrative
  embedding refresh) and the same infrastructure dependencies.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    VIEW_NARRATIVE,
    sha256_hex,
)
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from messaging.topics import (
    ENTITY_NARRATIVE_GENERATED as _ENTITY_NARRATIVE_GENERATED_TOPIC,  # type: ignore[import-untyped]
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

# BP-121: hard cap on narrative text sent to the embedding model.
# BGE-large uses a BERT encoder with a 512-token context window (~1500 chars).
# Sending more than this crashes the Ollama GGML runner with a context overflow.
# DeepInfra's BAAI/bge-large-en-v1.5 silently truncates but the cap is still
# applied for consistency and to avoid billing waste on over-length inputs.
_NARRATIVE_EMBED_MAX_CHARS = 1500

_NARRATIVE_GENERATED_SCHEMA_PATH = get_schema_path("entity.narrative.generated.v1.avsc")


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
        read_session_factory: Any = None,
    ) -> None:
        self._sf = session_factory
        # DEF-034 (Wave B-5): Phase 1 fetch + narrative-text build use the
        # read replica factory when configured; Phase 3 upsert stays on the
        # write factory.  Falls back to the write factory when no replica is
        # wired so existing call sites continue to work.
        self._read_session_factory: Any = read_session_factory if read_session_factory is not None else session_factory
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

        # DEF-034 (Wave B-5): the entire Phase 1 read (due rows + narrative
        # text build, both pure SELECTs) runs on the read replica.
        async with self._read_session_factory() as session:
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
        """Build narrative text for an entity.

        BP-542 fix: prefers LLM-generated prose from entity_narrative_versions
        (via current_narrative_version_id) over the deterministic claims template.
        The claims template is the fallback when no LLM narrative exists or when
        the stored narrative is shorter than 60 chars (name-only stub).
        """
        from sqlalchemy import text as sql_text

        # BP-542: check for LLM narrative before building the claims stub.
        # NarrativeGenerationWorker writes to entity_narrative_versions and sets
        # current_narrative_version_id; this worker previously ignored that path.
        llm_result = await session.execute(
            sql_text("""
SELECT env.narrative_text
FROM canonical_entities ce
JOIN entity_narrative_versions env ON env.version_id = ce.current_narrative_version_id
WHERE ce.entity_id = :entity_id
  AND env.narrative_text IS NOT NULL
LIMIT 1
"""),
            {"entity_id": str(entity_id)},
        )
        llm_row = llm_result.fetchone()
        if llm_row is not None:
            llm_text = str(llm_row[0])
            if len(llm_text) > 60:
                return llm_text

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


# ---------------------------------------------------------------------------
# NarrativeRefreshKafkaConsumer — PLAN-0074 T-C-05
# ---------------------------------------------------------------------------


class _NoOpUoW:
    """Minimal UoW satisfying BaseKafkaConsumer's context manager contract.

    NarrativeRefreshKafkaConsumer manages its own DB sessions inside
    process_message (R25 3-phase pattern), so the base class UoW is a no-op.
    """

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class NarrativeRefreshKafkaConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    """Kafka consumer for ``entity.narrative.generated.v1`` events (PLAN-0074 T-C-05).

    ADDITIVE path: the polling ``NarrativeRefreshWorker`` (hourly sweep) remains
    unchanged.  This consumer provides an immediate hot-path re-embedding when a
    new LLM narrative is generated, so the embedding reflects the latest text
    within seconds rather than waiting up to an hour for the next poll cycle.

    Processing per message:
      1. Deduplicate on event_id via ValkeyDedupMixin (BP-415/421 compliance).
      2. Parse EntityNarrativeGeneratedEvent from the Avro payload.
      3. Fetch the full ``narrative_text`` from ``entity_narrative_versions``
         using the ``version_id`` field (event payload only carries text length).
      4. Truncate to ``_NARRATIVE_EMBED_MAX_CHARS`` chars (BP-121 guard).
      5. Call ``llm_client.embed()`` with a single EmbeddingInput.
      6. Upsert the embedding into ``entity_embedding_state`` for view_type='narrative'.
      7. On embed failure: log ``narrative_kafka_embed_failed`` at WARNING and
         return WITHOUT dead-lettering — the polling worker will catch up.

    Idempotency contract
    --------------------
    Downstream writes (``entity_embedding_state`` UPSERT) use ``ON CONFLICT DO UPDATE``,
    so re-delivery of the same event_id is safe when Valkey is unavailable and
    ValkeyDedupMixin returns False (at-least-once fallback).

    Args:
    ----
        config:          Consumer configuration (topic, group, bootstrap).
        session_factory: async_sessionmaker for intelligence_db (write factory).
        llm_client:      FallbackChainClient instance wired with embedding adapters.
        embed_model_id:  Embedding model ID passed to EmbeddingInput.  Must match
                         the model used by NarrativeRefreshWorker to stay in the
                         same vector space.
        dedup_client:    Optional Valkey client for event deduplication.
                         None = at-least-once mode (safe — upsert is idempotent).

    """

    # DP-005: class-level prefix so the key namespace is stable across config
    # changes and instantiations (prefix does not depend on group_id).
    _dedup_prefix: str = "kg:dedup:narrative_refresh_kafka_consumer"

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        *,
        embed_model_id: str = _DEFAULT_EMBED_MODEL_ID,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._llm = llm_client
        self._embed_model_id = embed_model_id
        # ValkeyDedupMixin reads _dedup_client in is_duplicate / mark_processed.
        self._dedup_client = dedup_client

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Fetch narrative text, embed it, and upsert into entity_embedding_state.

        R25 3-phase pattern: Phase 1 = DB read (narrative text lookup), no session
        held during Phase 2 (embed() HTTP call), Phase 3 = DB write (upsert).
        """
        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]
        from sqlalchemy import text as sql_text

        from contracts.events.kg.entity_narrative_generated import (  # type: ignore[import-untyped]
            EntityNarrativeGeneratedEvent,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        event = EntityNarrativeGeneratedEvent.from_dict(value)
        entity_id = UUID(event.entity_id)
        version_id = UUID(event.version_id)

        # ── Phase 1: Read narrative_text from entity_narrative_versions ────────
        # Open a read session only to fetch the full text; close before embedding.
        narrative_text: str | None = None
        async with self._sf() as session:
            result = await session.execute(
                sql_text("""
SELECT narrative_text
FROM entity_narrative_versions
WHERE version_id = :version_id AND entity_id = :entity_id
LIMIT 1
"""),
                {"version_id": str(version_id), "entity_id": str(entity_id)},
            )
            row = result.fetchone()
            if row is not None:
                narrative_text = str(row[0])
        # DB session closed — no connection held during embedding HTTP call.

        if narrative_text is None:
            # Row not found — likely a race where the DB write has not committed yet.
            # Log and return; the hourly polling worker will pick it up on the
            # next cycle without any operator intervention required.
            logger.warning(  # type: ignore[no-any-return]
                "narrative_kafka_version_not_found",
                entity_id=str(entity_id),
                version_id=str(version_id),
                message="entity_narrative_versions row not found; embedding skipped (hourly worker will catch up)",
            )
            return

        # ── Phase 2: Truncate + embed (no DB session held) ────────────────────
        # BP-121: BGE-large BERT context window is 512 tokens (~1500 chars).
        # Always truncate before embedding to avoid context overflow crashes.
        truncated = narrative_text[:_NARRATIVE_EMBED_MAX_CHARS]
        source_hash = sha256_hex(truncated)

        embedding: list[float] | None = None
        try:
            outputs = await self._llm.embed([EmbeddingInput(text=truncated, model_id=self._embed_model_id)])
            if outputs:
                embedding = outputs[0].embedding
        except Exception:
            # Embed failure: log and return WITHOUT dead-lettering.
            # The hourly NarrativeRefreshWorker provides the catch-up guarantee;
            # dead-lettering a transient HTTP error would cause unnecessary noise
            # and interfere with the normal retry-storm prevention logic.
            logger.warning(  # type: ignore[no-any-return]
                "narrative_kafka_embed_failed",
                entity_id=str(entity_id),
                version_id=str(version_id),
                embed_model_id=self._embed_model_id,
                exc_info=True,
            )
            return

        # ── Phase 3: Upsert embedding into entity_embedding_state ─────────────
        async with self._sf() as session:
            emb_repo = EntityEmbeddingStateRepository(session)
            await emb_repo.upsert(
                entity_id,
                VIEW_NARRATIVE,
                embedding=embedding,
                model_id=self._embed_model_id if embedding is not None else None,
                source_text=truncated,
                source_hash=source_hash,
                # No scheduled next_refresh_at — this is an event-driven refresh.
                # The polling worker owns next_refresh_at scheduling; we pass None
                # and rely on the COALESCE in the upsert SQL to preserve the
                # existing next_refresh_at value.
                next_refresh_at=None,
            )
            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "narrative_kafka_embedding_refreshed",
            entity_id=str(entity_id),
            version_id=str(version_id),
            embed_model_id=self._embed_model_id,
            embedding_dim=len(embedding) if embedding else 0,
        )

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "narrative_kafka_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    # ------------------------------------------------------------------
    # Failure tracking (log-only)
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "narrative_kafka_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
            attempt=failure.attempt,
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "narrative_kafka_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "narrative_kafka_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ------------------------------------------------------------------
    # UoW (no-op — process_message manages its own sessions)
    # ------------------------------------------------------------------

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Decode entity.narrative.generated.v1 events.

        Uses Confluent-Avro (5-byte magic header + Avro body) with a JSON
        fallback for messages produced before the schema registry was wired.
        """
        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        path = schema_path or _NARRATIVE_GENERATED_SCHEMA_PATH
        if raw and raw[:1] == b"\x00":
            return deserialize_confluent_avro(path, raw)  # type: ignore[no-any-return]
        logger.warning(  # type: ignore[no-any-return]
            "narrative_kafka_legacy_json_payload",
            message="entity.narrative.generated.v1 message lacks Confluent magic byte; using JSON fallback",
        )
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _ENTITY_NARRATIVE_GENERATED_TOPIC:
            return _NARRATIVE_GENERATED_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
