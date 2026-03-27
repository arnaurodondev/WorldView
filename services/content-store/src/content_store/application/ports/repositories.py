"""Abstract repository interfaces (ports) for the Content Store application layer.

Use cases depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from content_store.domain.entities import CanonicalDocument, MinHashSignature


class DocumentRepositoryPort(ABC):
    """Port for canonical document storage."""

    @abstractmethod
    async def create(self, doc: CanonicalDocument) -> None: ...


class DedupHashRepositoryPort(ABC):
    """Port for deduplication hash lookups and insertions (Stage A + B)."""

    @abstractmethod
    async def check_exists(self, hash_type: str, hash_value: str) -> UUID | None: ...

    @abstractmethod
    async def insert_pair(self, doc_id: UUID, raw_hash: str, normalized_hash: str) -> None: ...


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
