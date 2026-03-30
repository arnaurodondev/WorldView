"""Abstract repository interfaces (ports) for the NLP Pipeline application layer.

Use cases depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


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
