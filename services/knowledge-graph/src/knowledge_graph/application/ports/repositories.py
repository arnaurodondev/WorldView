"""Abstract repository interfaces (ports) for the Knowledge Graph application layer.

Use cases depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

# ── Outbox topic constants ───────────────────────────────────────────────────
# Defined at the application layer so blocks and use cases can reference them
# without importing from infrastructure.

TOPIC_GRAPH_STATE_CHANGED = "graph.state.changed.v1"
TOPIC_CONTRADICTION = "intelligence.contradiction.v1"
TOPIC_RELATION_PROPOSED = "relation.type.proposed.v1"

# ── DLQ data transfer object ──────────────────────────────────────────────────


@dataclass
class DLQEntryData:
    """Application-layer representation of a dead-letter-queue entry."""

    dlq_id: UUID
    original_event_id: UUID
    topic: str
    error_detail: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


# ── DLQ admin port ────────────────────────────────────────────────────────────


class DLQRepositoryPort(ABC):
    """Port for DLQ admin operations (list, inspect, resolve)."""

    @abstractmethod
    async def list_open(self, limit: int = 100, offset: int = 0) -> tuple[list[DLQEntryData], int]: ...

    @abstractmethod
    async def get_by_id(self, dlq_id: UUID) -> DLQEntryData | None: ...

    @abstractmethod
    async def mark_resolved(self, dlq_id: UUID, note: str | None) -> bool: ...

    @abstractmethod
    async def commit(self) -> None: ...


# ── Outbox repository port ───────────────────────────────────────────────────


class OutboxRepositoryPort(ABC):
    """Port for outbox event appends (hot-path writes)."""

    @abstractmethod
    async def append(
        self,
        topic: str,
        partition_key: str,
        payload_avro: bytes,
    ) -> UUID: ...


# ── Relation type registry repository port ───────────────────────────────────


class RelationTypeRegistryRepositoryPort(ABC):
    """Port for relation type registry lookups (Block 11 canonicalization)."""

    @abstractmethod
    async def find_exact(self, candidate_type: str) -> dict[str, object] | None: ...

    @abstractmethod
    async def find_by_embedding(
        self,
        query_embedding: list[float],
        distance_threshold: float = 0.35,
        limit: int = 1,
    ) -> dict[str, object] | None: ...


# ── Contradiction repository port ────────────────────────────────────────────


class ContradictionRepositoryPort(ABC):
    """Port for contradiction detection reads/writes (Block 12b)."""

    @abstractmethod
    async def find_opposing_claims(
        self,
        subject_entity_id: UUID,
        claim_type: str,
        polarity: str,
        window_days: int = 90,
    ) -> list[dict[str, object]]: ...

    @abstractmethod
    async def insert_link(
        self,
        relation_evidence_id: UUID,
        claim_id: UUID,
        contradiction_type: str,
        strength: float,
        detected_at: datetime,
    ) -> UUID: ...


# ── Relation repository port ─────────────────────────────────────────────────


class RelationRepositoryPort(ABC):
    """Port for relation reads/writes (Block 12a graph materialization + API queries)."""

    @abstractmethod
    async def upsert(
        self,
        subject_entity_id: UUID,
        object_entity_id: UUID,
        canonical_type: str,
        semantic_mode: str,
        decay_class: str,
        decay_alpha: float,
        base_confidence: float,
    ) -> UUID: ...

    @abstractmethod
    async def list_for_entity(
        self,
        entity_id: UUID,
        *,
        min_confidence: float = 0.0,
        semantic_mode: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]: ...

    @abstractmethod
    async def list_filtered(
        self,
        *,
        subject_entity_id: UUID | None = None,
        object_entity_id: UUID | None = None,
        canonical_type: str | None = None,
        semantic_mode: str | None = None,
        min_confidence: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]: ...

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]: ...

    @abstractmethod
    async def find_competes_with_batch(
        self,
        entity_id: UUID,
        candidate_ids: list[UUID],
        min_confidence: float = 0.3,
    ) -> dict[UUID, tuple[bool, float | None]]:
        """Return a mapping of candidate_id → (has_relation, confidence).

        Checks both directions (entity_id → candidate AND candidate → entity_id).
        Only candidates with an active ``competes_with`` relation meeting
        ``min_confidence`` are included in the result dict.

        Returns an empty dict when ``candidate_ids`` is empty.
        """


# ── Relation evidence repository port ────────────────────────────────────────


class RelationEvidenceRepositoryPort(ABC):
    """Port for relation evidence inserts (hot-path staging) and read queries."""

    @abstractmethod
    async def insert_raw(
        self,
        subject_entity_id: UUID,
        object_entity_id: UUID,
        source_document_id: UUID,
        extraction_confidence: float,
        source_trust_weight: float,
        evidence_date: datetime,
        *,
        canonical_type: str | None = None,
        polarity: str = "positive",
        claim_id: UUID | None = None,
        chunk_id: UUID | None = None,
        is_backfill: bool = False,
        entity_provisional: bool = False,
        provisional_queue_id: UUID | None = None,
        evidence_text: str | None = None,
    ) -> UUID: ...

    @abstractmethod
    async def get_evidence_snippets_batch(
        self,
        relation_ids: list[UUID],
        limit_per_relation: int = 3,
    ) -> dict[UUID, list[str]]:
        """Return top-N evidence snippets per relation in a single CTE query.

        Ordered by extraction_confidence DESC NULLS LAST, evidence_date DESC NULLS LAST.
        Returns {} for any relation_id with no evidence text.
        # TODO(PRD-0074): upgrade to denormalized top_evidence_snippets JSONB on relations
        """


# ── Canonical entity repository port ─────────────────────────────────────────


class CanonicalEntityRepositoryPort(ABC):
    """Port for canonical entity lookups (API queries)."""

    @abstractmethod
    async def get(self, entity_id: UUID) -> dict[str, object] | None: ...

    @abstractmethod
    async def exists(self, entity_id: UUID) -> bool: ...

    @abstractmethod
    async def get_batch(self, entity_ids: list[UUID]) -> list[dict[str, object]]:
        """Fetch multiple canonical entities in a single WHERE entity_id = ANY(:ids) query.

        Returns only entities that exist — missing IDs are silently omitted.
        """

    @abstractmethod
    async def find_by_ticker(self, ticker: str) -> dict[str, object] | None:
        """Find entity by ticker symbol (case-insensitive). Returns None if not found."""


# ── Entity embedding ANN port (PRD-0017 §6.5) ────────────────────────────────


@dataclass(frozen=True)
class AnnResult:
    """Single nearest-neighbour result from a pgvector ANN query.

    ``distance`` is cosine distance in [0, 2]: 0 = identical, 2 = opposite.
    To convert to similarity: ``similarity = 1.0 - distance``.
    """

    entity_id: UUID
    distance: float


class EntityEmbeddingANNRepositoryPort(ABC):
    """Port for pgvector ANN queries on ``entity_embedding_state`` (PRD-0017 §6.5)."""

    @abstractmethod
    async def find_nearest(
        self,
        query_embedding: list[float],
        view_type: str,
        limit: int = 40,
        exclude_entity_id: UUID | None = None,
        entity_types: list[str] | None = None,
    ) -> list[AnnResult]:
        """Return nearest neighbours by cosine distance, ascending.

        Args:
        ----
            query_embedding: The query vector (must match stored embedding dimension).
            view_type:        Which embedding view to search (e.g. ``'fundamentals_ohlcv'``).
            limit:            Maximum number of results to return.
            exclude_entity_id: If provided, exclude this entity from results (self-exclusion).
            entity_types:     If provided, restrict results to entities with these types.
                              Applied via JOIN on ``canonical_entities``.

        Returns:
        -------
            Sorted ascending by ``distance`` (nearest first).

        """

    @abstractmethod
    async def get_embedding(
        self,
        entity_id: UUID,
        view_type: str,
    ) -> list[float] | None:
        """Fetch the stored embedding vector for a given entity + view, or None.

        Returns None when no row exists or the embedding column is NULL.
        Used by the use case to check embedding availability before ANN search.
        """
