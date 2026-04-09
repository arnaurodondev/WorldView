"""Port protocols for repository interfaces — application layer boundary.

Use cases depend only on these protocols, never on infrastructure classes directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from content_ingestion.domain.entities import ContentIngestionTask


# ── Existing ports ───────────────────────────────────────────────────────────


@runtime_checkable
class FetchLogPort(Protocol):
    """Port for article fetch log repository."""

    async def exists_by_url_hash(self, url_hash: str) -> bool: ...

    async def create(
        self,
        *,
        url: str,
        url_hash: str,
        source_id: UUID | None,
        http_status: int,
        byte_size: int,
        fetched_at: datetime,
        published_at: datetime | None,
        is_backfill: bool,
        row_id: UUID,
    ) -> Any: ...

    async def count_by_source_since(self, source_id: UUID, since: datetime) -> int: ...


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

    async def count_pending(self) -> int: ...


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

    async def delete_object(self, key: str) -> None:
        """Delete a bronze object by key (best-effort orphan GC)."""
        ...


# ── New ports (PLAN-0009 Wave A-1) ──────────────────────────────────────────


@runtime_checkable
class SourcePort(Protocol):
    """Port for the sources repository."""

    async def get_all(self) -> list[Any]: ...

    async def get_by_id(self, source_id: UUID) -> Any: ...

    async def list_enabled(self) -> list[Any]: ...

    async def create(
        self,
        name: str,
        source_type: str,
        config: dict[str, Any],
        enabled: bool = True,
    ) -> Any: ...

    async def update(self, source_id: UUID, **kwargs: Any) -> Any: ...


@runtime_checkable
class TaskPort(Protocol):
    """Port for the content_ingestion_tasks repository."""

    async def add(self, task: ContentIngestionTask) -> None: ...

    async def add_many_idempotent(self, tasks: list[ContentIngestionTask]) -> int: ...

    async def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> list[ContentIngestionTask]: ...

    async def update_status(
        self,
        task_id: UUID,
        status: Any,
        error_detail: str | None = None,
    ) -> None: ...

    async def has_active_task(self, source_id: UUID) -> bool: ...

    async def recover_expired_leases(self, now: datetime, lease_timeout_seconds: int) -> int: ...

    async def count_by_status(self) -> dict[str, int]: ...


@runtime_checkable
class AdapterStatePort(Protocol):
    """Port for the source_adapter_state repository."""

    async def get(self, source_id: UUID) -> Any: ...

    async def upsert(
        self,
        source_id: UUID,
        *,
        last_watermark: datetime | None = None,
        last_cursor: str | None = None,
        last_run_at: datetime | None = None,
        next_run_at: datetime | None = None,
        error_count: int | None = None,
        last_error: str | None = None,
    ) -> Any: ...

    async def reset_errors(self, source_id: UUID) -> None: ...

    async def get_all(self) -> list[Any]: ...


@runtime_checkable
class DLQPort(Protocol):
    """Port for the dead_letter_queue repository."""

    async def list_open(self, limit: int = 100, offset: int = 0) -> tuple[list[Any], int]: ...

    async def get_by_id(self, dlq_id: UUID) -> Any: ...

    async def mark_resolved(self, dlq_id: UUID, note: str) -> None: ...

    async def requeue(self, dlq_id: UUID) -> UUID | None: ...

    async def count_failed(self) -> int: ...


@runtime_checkable
class PredictionMarketFetchLogPort(Protocol):
    """Port for the prediction_market_fetch_log repository."""

    async def exists_by_market_snapshot(self, market_id: str, snapshot_at: datetime) -> bool: ...

    async def create_market_fetch_log(
        self,
        *,
        source_id: UUID | None,
        market_id: str,
        snapshot_at: datetime,
        resolution_status: str,
        fetched_at: datetime,
    ) -> UUID | None:
        """Insert a fetch log row; return the UUID or None if already exists."""
        ...
