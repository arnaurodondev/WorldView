"""Shared enrichment logic for ProvisionalEnrichmentWorker and ProvisionalQueuedConsumer.

Both the polling sweep worker (provisional_enrichment.py) and the hot-path Kafka
consumer (provisional_queued_consumer.py) need to run the same LLM extraction,
embedding, and DB persistence steps.  This module provides module-level async
functions so both call sites can share logic without circular imports.

ARCH-003 contract: no DB session is held during extract_entity_profile or
compute_embedding — callers acquire a session, release it, do the I/O, then
acquire a new session for persist_enrichment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    EntityEmbeddingStateRepository,
)
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

_ENTITY_CANONICAL_CREATED_SCHEMA_PATH = get_schema_path("entity.canonical.created.v1.avsc")
_ENTITY_DIRTIED_SCHEMA_PATH = get_schema_path("entity.dirtied.v1.avsc")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_EXTRACT_MODEL_ID = "kg-entity-profile-v1"


def _build_dirtied_event(entity_id: UUID, dirty_reason: str = "profile_updated") -> bytes:
    """Build a fully-populated entity.dirtied.v1 Confluent-Avro payload.

    B-3 fix: previously callers emitted ``{"entity_id": "<uuid>"}`` which is
    missing ``event_id``, ``event_type``, ``schema_version``, ``occurred_at``,
    and ``dirty_reason`` — all required by the Avro schema at
    ``infra/kafka/schemas/entity.dirtied.v1.avsc``.

    PLAN-0062 R28 fix: migrated from json.dumps to serialize_confluent_avro so
    that entity.dirtied.v1 uses the Confluent 5-byte wire-format header,
    consistent with all other producer paths.
    """
    from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

    return serialize_confluent_avro(
        _ENTITY_DIRTIED_SCHEMA_PATH,
        {
            "event_id": str(new_uuid7()),
            "event_type": "entity.dirtied",
            "schema_version": 1,
            "occurred_at": utc_now().isoformat(),
            "entity_id": str(entity_id),
            "dirty_reason": dirty_reason,
            "source_doc_id": None,
            "correlation_id": None,
        },
    )


async def extract_entity_profile(
    llm_client: FallbackChainClient,
    mention_text: str,
    mention_class: str,
    context_snippet: str,
) -> dict[str, Any] | None:
    """Call the extraction LLM to produce a structured entity profile.

    No DB session needed — pure HTTP call via FallbackChainClient.

    Returns a dict with keys: canonical_name, entity_type, ticker, isin, aliases.
    Returns None if the LLM chain fails or returns an empty result.
    """
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
    result = await llm_client.extract(inp, entity_id=None)
    if result is None:
        return None
    return result.result  # type: ignore[return-value]


async def compute_embedding(
    llm_client: FallbackChainClient,
    entity_id: UUID | None,
    source_text: str,
    embed_model_id: str,
) -> list[float] | None:
    """Compute a definition embedding via the LLM chain.

    No DB session needed — pure HTTP call (ARCH-003).
    """
    from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

    inp = EmbeddingInput(text=source_text, model_id=embed_model_id)
    outputs = await llm_client.embed([inp], entity_id=entity_id)
    return outputs[0].embedding if outputs else None


async def persist_enrichment(
    session: AsyncSession,
    queue_id: UUID,
    mention_text: str,
    profile: dict[str, Any],
    embedding: list[float] | None = None,
    embed_model_id: str = "bge-large:latest",
) -> UUID | None:
    """Persist an LLM-extracted entity profile to intelligence_db.

    Performs all DB writes for a single provisional entity:
      - canonical_entities INSERT
      - entity_aliases INSERTs (mechanical + LLM with collision check)
      - entity_embedding_state rows
      - embedding upsert (if provided)
      - relation_evidence_raw provisional flag clear
      - entity.canonical.created.v1 outbox entry

    Session-only — no external HTTP/LLM calls (ARCH-003).
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
    from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

    canonical_name: str = profile.get("canonical_name") or mention_text
    entity_type: str = profile.get("entity_type") or str(profile.get("mention_class", "unknown"))
    ticker: str | None = profile.get("ticker")
    isin: str | None = profile.get("isin")

    # QA-iter1 (PLAN-0062 SA-005 fix): pre-validate the Avro payload BEFORE any
    # DB writes.  The polling worker (provisional_enrichment.py) commits the
    # batch session in a finally-style block — if serialize_confluent_avro
    # raised AFTER the canonical-entity INSERT it would orphan the entity row
    # without an outbox event (DB committed, no Kafka event ever produced).
    # By serializing first we either fail-fast (no DB writes) or have valid
    # bytes ready when the outbox INSERT runs at the end of this function.
    entity_id_str = str(new_uuid7())
    avro_record: dict[str, Any] = {
        "event_id": str(new_uuid7()),
        "event_type": "entity.canonical.created",
        "schema_version": 1,
        "occurred_at": utc_now().isoformat(),
        "entity_id": entity_id_str,
        "canonical_name": canonical_name,
        "entity_type": entity_type,
        "provisional_queue_id": str(queue_id),
        "alias_texts": [canonical_name, *([ticker.upper()] if ticker else []), *([isin.upper()] if isin else [])],
        "correlation_id": None,
    }
    avro_payload_bytes = serialize_confluent_avro(_ENTITY_CANONICAL_CREATED_SCHEMA_PATH, avro_record)

    entity_repo = CanonicalEntityRepository(session)
    entity_id = await entity_repo.create(  # type: ignore[attr-defined]
        canonical_name=canonical_name,
        entity_type=entity_type,
        ticker=ticker,
        isin=isin,
    )
    # The repo generates its own UUIDv7 — re-serialize with the actual entity_id
    # to keep the outbox bytes consistent with the DB row.  This second
    # serialize_confluent_avro call uses an identical record shape, so it is
    # equally safe to fail before any further DB work.
    avro_record["entity_id"] = str(entity_id)
    avro_payload_bytes = serialize_confluent_avro(_ENTITY_CANONICAL_CREATED_SCHEMA_PATH, avro_record)

    alias_repo = EntityAliasRepository(session)
    normalized_name = canonical_name.lower().strip()
    await alias_repo.insert(entity_id, canonical_name, normalized_name, "EXACT", "provisional_enrichment")

    if ticker:
        await alias_repo.insert(entity_id, ticker, ticker.upper(), "TICKER", "provisional_enrichment")
    if isin:
        await alias_repo.insert(entity_id, isin, isin.upper(), "ISIN", "provisional_enrichment")

    llm_aliases: list[str] = profile.get("aliases") or []
    for alias in llm_aliases[:5]:
        normalized = alias.lower().strip()
        existing = await alias_repo.find_exact(normalized)
        if existing and existing["entity_id"] != entity_id:
            logger.warning(  # type: ignore[no-any-return]
                "provisional_enrichment_alias_collision",
                alias=alias,
                existing_entity_id=str(existing["entity_id"]),
                new_entity_id=str(entity_id),
            )
            continue
        await alias_repo.insert(entity_id, alias, normalized, "LLM", "provisional_enrichment")

    emb_repo = EntityEmbeddingStateRepository(session)
    await emb_repo.ensure_rows_exist(entity_id, entity_type)

    if canonical_name and embedding is not None:
        await _write_embedding(entity_id, canonical_name, embedding, emb_repo, embed_model_id)

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

    outbox_repo = OutboxRepository(session)
    # QA-iter1 (PLAN-0062): payload bytes were pre-serialized at the top of
    # this function — the call there fails-fast if the record dict is invalid,
    # preventing partial DB state without an outbox row (BP-313 / SA-005).
    await outbox_repo.append(
        topic="entity.canonical.created.v1",
        partition_key=str(entity_id),
        payload_avro=avro_payload_bytes,
    )

    return entity_id  # type: ignore[no-any-return]


async def _write_embedding(
    entity_id: UUID,
    source_text: str,
    embedding: list[float] | None,
    emb_repo: EntityEmbeddingStateRepository,
    embed_model_id: str,
) -> None:
    """Write a pre-computed embedding vector to entity_embedding_state (session-only)."""
    from datetime import timedelta

    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
        VIEW_DEFINITION,
        sha256_hex,
    )

    await emb_repo.upsert(
        entity_id,
        VIEW_DEFINITION,
        embedding=embedding,
        model_id=embed_model_id if embedding else None,
        source_text=source_text,
        source_hash=sha256_hex(source_text),
        next_refresh_at=utc_now() + timedelta(days=90),  # type: ignore[no-any-return, operator]
    )


async def apply_retry_transition(
    session: AsyncSession,
    queue_id: UUID,
    max_retries: int,
) -> bool:
    """Atomically increment retry_count and decide terminal state in one SQL round-trip.

    The DB authoritatively reads the current ``retry_count`` and computes the
    new status with a SQL ``CASE`` expression, so we never depend on a stale
    caller-supplied count.  ``RETURNING (status = 'failed')`` exposes the outcome
    to Python so the caller can increment the appropriate Prometheus counter.

    Returns True if the row was transitioned to 'failed' (terminal), False if it
    was reset to 'pending' for another attempt.

    This function does NOT increment ``s7_provisional_enrichment_failed_total`` —
    callers that need the counter (the worker's ``_apply_retry``) must check
    the return value and call ``inc()`` themselves so existing test patch paths
    are preserved.
    """
    from sqlalchemy import text

    result = await session.execute(
        text("""
UPDATE provisional_entity_queue
SET retry_count = LEAST(retry_count + 1, :max_retries),
    status = CASE
        WHEN retry_count + 1 >= :max_retries THEN 'failed'
        ELSE 'pending'
    END
WHERE queue_id = :queue_id
RETURNING (status = 'failed') AS is_terminal
"""),
        {"queue_id": str(queue_id), "max_retries": max_retries},
    )
    row = result.fetchone()
    if row is None:
        # Row no longer exists (very rare — would imply concurrent delete).
        return False
    return bool(row[0])
