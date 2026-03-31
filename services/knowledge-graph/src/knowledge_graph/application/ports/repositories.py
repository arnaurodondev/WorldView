"""Abstract repository interfaces (ports) for the Knowledge Graph application layer.

Use cases depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
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


# ── Relation evidence repository port ────────────────────────────────────────


class RelationEvidenceRepositoryPort(ABC):
    """Port for relation evidence inserts (hot-path staging)."""

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
    ) -> UUID: ...


# ── Canonical entity repository port ─────────────────────────────────────────


class CanonicalEntityRepositoryPort(ABC):
    """Port for canonical entity lookups (API queries)."""

    @abstractmethod
    async def get(self, entity_id: UUID) -> dict[str, object] | None: ...

    @abstractmethod
    async def exists(self, entity_id: UUID) -> bool: ...
