"""Block 11 — Relation type canonicalization (PRD §6.7 Block 11).

3-step pipeline:
  1. Exact match against ``relation_type_registry.canonical_type``.
  2. ANN soft-map via cosine distance on ``relation_type_registry.embedding``
     (VECTOR 1024) — threshold ≤ 0.35.
  3. No match → emit ``relation.type.proposed.v1`` via outbox, return
     ``canonical_type=None`` WITHOUT raising.  Unknown types never fail
     the message.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.ports.repositories import (
    TOPIC_RELATION_PROPOSED,
)
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import (  # type: ignore[import-untyped]
    serialize_confluent_avro,
)

# PLAN-0062 F-006: producer-side R28 enforcement — emit Confluent-Avro framed
# bytes (5-byte magic+schema-id header + Avro body) for ``relation.type.proposed.v1``
# instead of raw ``json.dumps(...).encode()``.  Resolved at import time so
# production code and tests share the same path.
_RELATION_TYPE_PROPOSED_SCHEMA_PATH = get_schema_path("relation.type.proposed.v1.avsc")

if TYPE_CHECKING:
    from knowledge_graph.application.ports.repositories import (
        OutboxRepositoryPort as OutboxRepository,
    )
    from knowledge_graph.application.ports.repositories import (
        RelationTypeRegistryRepositoryPort as RelationTypeRegistryRepository,
    )

# ---------------------------------------------------------------------------
# Protocol for the embedding client (duck-typed — no ml-clients runtime dep)
# ---------------------------------------------------------------------------


class EmbeddingClientProtocol:  # (mypy structural subtyping)
    """Protocol: ``embed(text) -> list[float]``."""

    async def embed(self, text: str) -> list[float]:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CanonicalizationResult:
    """Outcome of the 3-step canonicalization.

    ``canonical_type`` is ``None`` when the type was proposed (Step 3).
    ``step`` records which step resolved the type.
    """

    canonical_type: str | None
    semantic_mode: str | None
    decay_class: str | None
    decay_alpha: float | None
    base_confidence: float | None
    step: Literal["exact", "soft_mapped", "proposed"]


# ---------------------------------------------------------------------------
# Main block function
# ---------------------------------------------------------------------------


async def canonicalize_relation_type(
    raw_type: str,
    semantic_mode_hint: str,
    *,
    subject_entity_id: UUID,
    object_entity_id: UUID,
    source_doc_id: UUID | None,
    registry_repo: RelationTypeRegistryRepository,
    outbox_repo: OutboxRepository,
    embedding_client: EmbeddingClientProtocol,
    distance_threshold: float = 0.35,
    correlation_id: str | None = None,
) -> CanonicalizationResult:
    """Canonicalize *raw_type* via the 3-step PRD §6.7 Block 11 pipeline.

    Always returns a :class:`CanonicalizationResult`.  When the type is
    unknown it emits ``relation.type.proposed.v1`` and returns
    ``canonical_type=None`` — it does **not** raise.

    Args:
    ----
        raw_type: Raw relation type string from the LLM extraction.
        semantic_mode_hint: Hint from the enriched message (RELATION_STATE or
            TEMPORAL_CLAIM).  Used as fallback when registry lookup fails.
        subject_entity_id: Subject canonical entity ID (for the proposal).
        object_entity_id: Object canonical entity ID (for the proposal).
        source_doc_id: Source document ID (for the proposal).
        registry_repo: Repository for ``relation_type_registry``.
        outbox_repo: Repository for ``outbox_events`` (appends proposal).
        embedding_client: Client that can embed text.
        distance_threshold: Maximum cosine distance for soft-map (default 0.35).
        correlation_id: Propagated correlation ID.

    Returns:
    -------
        :class:`CanonicalizationResult` with ``canonical_type=None`` if proposed.

    """
    # ------------------------------------------------------------------
    # Step 1 — Exact match (PLAN-0072 T-72-1-02: normalize before lookup)
    # ------------------------------------------------------------------
    # LLM outputs lowercase ("competes_with") while registry seeds are
    # lowercase too, but some historical payloads had UPPER or mixed case.
    # Normalize here so the exact-match is always case-insensitive.
    normalized_raw_type = raw_type.lower().strip().replace(" ", "_")
    exact = await registry_repo.find_exact(normalized_raw_type)
    if exact:
        return CanonicalizationResult(
            canonical_type=str(exact["canonical_type"]),
            semantic_mode=str(exact["semantic_mode"]),
            decay_class=str(exact["decay_class"]),
            decay_alpha=float(exact["decay_alpha"]),  # type: ignore[arg-type]
            base_confidence=float(exact["base_confidence"]),  # type: ignore[arg-type]
            step="exact",
        )

    # ------------------------------------------------------------------
    # Step 2 — ANN soft-map via embedding cosine distance
    # ------------------------------------------------------------------
    embedding = await embedding_client.embed(raw_type)
    soft = await registry_repo.find_by_embedding(
        embedding,
        distance_threshold=distance_threshold,
    )
    if soft:
        return CanonicalizationResult(
            canonical_type=str(soft["canonical_type"]),
            semantic_mode=str(soft["semantic_mode"]),
            decay_class=str(soft["decay_class"]),
            decay_alpha=float(soft.get("decay_alpha", 0.0)),  # type: ignore[arg-type]
            base_confidence=float(soft["base_confidence"]),  # type: ignore[arg-type]
            step="soft_mapped",
        )

    # ------------------------------------------------------------------
    # Step 3 — Unknown type: propose via outbox, return None
    # ------------------------------------------------------------------
    proposal_payload = {
        "event_id": str(new_uuid7()),
        "event_type": "relation.type.proposed",
        "schema_version": 1,
        "occurred_at": utc_now().isoformat(),
        "proposed_type": raw_type,
        "semantic_mode": semantic_mode_hint,
        "suggested_decay_class": None,
        "example_subject_entity_id": str(subject_entity_id),
        "example_object_entity_id": str(object_entity_id),
        "example_evidence_text": None,
        "source_doc_id": str(source_doc_id) if source_doc_id else None,
        "correlation_id": correlation_id,
    }
    # PLAN-0062 F-006 / DS F-001: build Avro bytes BEFORE the outbox append so
    # a serialization failure aborts the transaction instead of poisoning the
    # outbox with a half-written row.  Confluent wire format with magic byte
    # ``0x00`` + 4-byte schema-id placeholder.
    payload_avro_bytes = serialize_confluent_avro(
        _RELATION_TYPE_PROPOSED_SCHEMA_PATH,
        proposal_payload,
    )
    await outbox_repo.append(  # type: ignore[call-arg]
        topic=TOPIC_RELATION_PROPOSED,
        partition_key=str(subject_entity_id),
        payload_avro=payload_avro_bytes,
    )

    return CanonicalizationResult(
        canonical_type=None,
        semantic_mode=None,
        decay_class=None,
        decay_alpha=None,
        base_confidence=None,
        step="proposed",
    )
