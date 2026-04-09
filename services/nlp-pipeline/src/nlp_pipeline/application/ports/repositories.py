"""Abstract repository interfaces (ports) for the NLP Pipeline application layer.

Use cases depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    from nlp_pipeline.domain.models import ArticlePriceImpact


# ── DLQ data transfer object ──────────────────────────────────────────────────


@dataclass
class DLQEntryData:
    """Application-layer representation of a dead-letter-queue entry.

    Returned by ``DLQRepositoryPort`` — no infrastructure imports required.
    ``payload_avro`` is included so the requeue operation can reconstruct
    the outbox event from the stored Avro bytes.
    """

    dlq_id: UUID
    original_event_id: UUID
    topic: str
    payload_avro: bytes
    error_detail: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


# ── DLQ admin port ────────────────────────────────────────────────────────────


class DLQRepositoryPort(ABC):
    """Port for DLQ admin operations (list, inspect, retry, resolve)."""

    @abstractmethod
    async def list_open(self, limit: int = 100, offset: int = 0) -> tuple[list[DLQEntryData], int]: ...

    @abstractmethod
    async def get_by_id(self, dlq_id: UUID) -> DLQEntryData | None: ...

    @abstractmethod
    async def requeue(self, dlq_id: UUID, payload_avro: bytes, topic: str, partition_key: str) -> UUID: ...

    @abstractmethod
    async def mark_resolved(self, dlq_id: UUID, note: str) -> None: ...

    @abstractmethod
    async def commit(self) -> None: ...


# ── Signals query port ───────────────────────────────────────────────────────


class SignalsQueryPort(ABC):
    """Port for signals/entity/article read-model queries (API layer).

    Abstracts ORM model access so that use cases in the application layer
    never import from infrastructure.
    """

    @abstractmethod
    async def list_signal_events(
        self,
        limit: int,
        offset: int,
        doc_id: UUID | None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return outbox events for the signal topic, with total count."""
        ...

    @abstractmethod
    async def search_entity_mentions(
        self,
        q: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return entity mentions matching substring, with total count."""
        ...

    @abstractmethod
    async def get_entity_detail(self, entity_id: UUID) -> dict[str, Any] | None:
        """Return aggregated entity mention stats for a given entity_id."""
        ...

    @abstractmethod
    async def get_entity_articles(
        self,
        entity_id: UUID,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return articles that mention a given entity, with total count."""
        ...

    @abstractmethod
    async def vector_search_sections(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Return sections for vector search (keyword ILIKE fallback until embedding client injected)."""
        ...

    @abstractmethod
    async def find_routing_decision(self, doc_id: UUID) -> bool:
        """Return True if a routing decision exists for the given doc_id."""
        ...

    @abstractmethod
    async def insert_outbox_event(
        self,
        event_id: UUID,
        topic: str,
        partition_key: str,
        payload_avro: bytes,
    ) -> None:
        """Insert an outbox event and commit."""
        ...


# ── ChunkTextStore port ───────────────────────────────────────────────────────


class ChunkTextStorePort(ABC):
    """Port for persisting and retrieving chunk text via object storage.

    Implemented by ``MinIOChunkTextStore`` in the infrastructure layer.
    The port decouples Block 7 and the search use case from MinIO details.
    """

    @abstractmethod
    async def put(self, chunk_id: UUID, doc_id: UUID, text: str) -> str:
        """Upload chunk text; return the storage key (e.g. MinIO object key)."""
        ...

    @abstractmethod
    async def get_batch(self, key_map: dict[UUID, str]) -> dict[UUID, str]:
        """Fetch texts for multiple chunks concurrently.

        Args:
            key_map: Mapping of chunk_id → storage_key for chunks to fetch.

        Returns:
            Mapping of chunk_id → text for successfully retrieved chunks.
            Chunks whose key is missing or whose fetch fails are omitted.
        """
        ...


# ── DocumentSourceMetadata port ───────────────────────────────────────────────


class DocumentSourceMetadataRepository(ABC):
    """Port for caching article citation metadata for S8 RAG retrieval.

    Populated by the S6 article consumer as a best-effort side effect.
    Queried by S8 to attach citation data to chunk search results.
    """

    @abstractmethod
    async def upsert(self, metadata: Any) -> None:
        """Persist metadata; ON CONFLICT (doc_id) DO NOTHING — idempotent."""
        ...

    @abstractmethod
    async def batch_get(self, doc_ids: list[UUID]) -> dict[UUID, Any]:
        """Return metadata keyed by doc_id; only present doc_ids are included."""
        ...


# ── PriceImpact repository port ───────────────────────────────────────────────


class PriceImpactRepositoryPort(ABC):
    """Port for article price-impact label persistence (PRD-0020 §6.5).

    Used by ``PriceImpactLabellingWorker`` (writes) and Block 5 (reads).
    Concrete implementation: ``ArticlePriceImpactRepository`` in infrastructure.
    """

    @abstractmethod
    async def upsert(self, impact: ArticlePriceImpact) -> None:
        """Persist a price-impact label; ON CONFLICT (article_id) DO NOTHING — idempotent."""
        ...

    @abstractmethod
    async def get_by_article_id(self, article_id: UUID) -> ArticlePriceImpact | None:
        """Return the label for a given article, or ``None`` if not yet labelled."""
        ...

    @abstractmethod
    async def get_max_impact_for_doc(self, doc_id: UUID) -> Decimal:
        """Return the max ``impact_score`` across all entities for an article.

        Returns ``Decimal("0.0")`` when no labels exist (article not yet labelled).
        Block 5 uses this to up-weight articles that coincide with large price moves.
        """
        ...

    @abstractmethod
    async def get_unlabelled_articles(self, min_age_hours: int, batch_size: int) -> list[tuple[UUID, list[UUID]]]:
        """Return ``[(doc_id, [entity_id, ...])]`` for unlabelled articles.

        Selects articles that:
          - have at least one resolved entity_mention
          - are NOT already in ``article_price_impacts``
          - were published more than ``min_age_hours`` ago (OHLCV bar must be closed)

        Returns at most ``batch_size`` rows, grouped by ``doc_id``.
        """
        ...
