"""Abstract repository interfaces (ports) for the Content Store application layer.

Use cases depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from content_store.domain.entities import CanonicalDocument, MinHashSignature

# ── DLQ data transfer object ──────────────────────────────────────────────────


@dataclass
class DLQEntryData:
    """Application-layer representation of a dead-letter-queue entry.

    Returned by ``DLQRepositoryPort`` — no infrastructure imports required.
    """

    dlq_id: UUID
    original_event_id: UUID
    topic: str
    error_detail: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


# ── Document metadata DTO ────────────────────────────────────────────────────


@dataclass
class DocumentMetadataDTO:
    """Lightweight document metadata returned by the batch lookup endpoint.

    ``source_name`` is always ``None`` — the ``documents`` table has no such
    column.  S8 derives it from ``document_source_metadata`` in S6.
    """

    doc_id: UUID
    title: str | None
    url: str | None
    published_at: datetime | None
    source_name: str | None
    source_type: str | None
    word_count: int | None


class DocumentRepositoryPort(ABC):
    """Port for canonical document storage."""

    @abstractmethod
    async def create(self, doc: CanonicalDocument) -> None: ...

    @abstractmethod
    async def batch_get_metadata(self, doc_ids: list[UUID]) -> list[DocumentMetadataDTO]: ...


class DedupHashRepositoryPort(ABC):
    """Port for deduplication hash lookups and insertions (Stage A + B)."""

    @abstractmethod
    async def check_exists(self, hash_type: str, hash_value: str, tenant_id: UUID | None = None) -> UUID | None: ...

    @abstractmethod
    async def insert_pair(
        self,
        doc_id: UUID,
        raw_hash: str,
        normalized_hash: str,
        tenant_id: UUID | None = None,
    ) -> None: ...


class MinHashRepositoryPort(ABC):
    """Port for MinHash signature storage and retrieval (Stage C)."""

    @abstractmethod
    async def create_signature(self, sig: MinHashSignature) -> None: ...

    @abstractmethod
    async def get_signature_by_doc_id(self, doc_id: UUID) -> Any: ...


class OutboxPort(ABC):
    """Port for transactional outbox operations."""

    @abstractmethod
    async def append(
        self,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        topic: str,
        payload: dict,
    ) -> None: ...

    @abstractmethod
    async def move_to_dead_letter(self, record_id: UUID, error_detail: str = "") -> bool: ...


# ── DLQ admin port ────────────────────────────────────────────────────────────


class DLQRepositoryPort(ABC):
    """Port for DLQ admin operations (list, inspect, resolve, requeue)."""

    @abstractmethod
    async def list_open(self, limit: int = 100, offset: int = 0) -> tuple[list[DLQEntryData], int]: ...

    @abstractmethod
    async def get_by_id(self, dlq_id: UUID) -> DLQEntryData | None: ...

    @abstractmethod
    async def mark_resolved(self, dlq_id: UUID, note: str) -> None: ...

    @abstractmethod
    async def requeue(self, dlq_id: UUID) -> UUID | None: ...

    @abstractmethod
    async def commit(self) -> None: ...
