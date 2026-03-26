"""Port protocols for repository interfaces — application layer boundary.

Use cases depend only on these protocols, never on infrastructure classes directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class FetchLogPort(Protocol):
    """Port for article fetch log repository."""

    async def exists_by_url_hash(self, url_hash: str) -> bool: ...

    async def create(
        self,
        *,
        url: str,
        url_hash: str,
        source_id: UUID,
        http_status: int,
        byte_size: int,
        fetched_at: datetime,
        published_at: datetime | None,
        is_backfill: bool,
        row_id: UUID,
    ) -> Any: ...


@runtime_checkable
class OutboxPort(Protocol):
    """Port for transactional outbox repository."""

    async def append(
        self,
        *,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        topic: str,
        payload: dict[str, Any],
    ) -> Any: ...


@runtime_checkable
class BronzeStoragePort(Protocol):
    """Port for MinIO bronze-tier storage adapter."""

    async def put_object(
        self,
        *,
        source_type: str,
        url_hash: str,
        raw_bytes: bytes,
        url: str,
        fetched_at: str,
        published_at: str | None,
        is_backfill: bool,
    ) -> str: ...
