"""DLQ read-only use cases — list and get entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.application.ports.unit_of_work import ReadOnlyUnitOfWork

logger = get_logger(__name__)


@dataclass(frozen=True)
class DLQEntryDTO:
    """Read-only DTO for a DLQ entry."""

    dlq_id: UUID
    original_event_id: UUID
    topic: str
    error_detail: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


@dataclass(frozen=True)
class DLQListResult:
    """Paginated DLQ list result."""

    entries: list[DLQEntryDTO]
    count: int


def _to_dto(entry: object) -> DLQEntryDTO:
    """Map a DLQ repository object to a DTO."""
    return DLQEntryDTO(
        dlq_id=entry.dlq_id,  # type: ignore[attr-defined]
        original_event_id=entry.original_event_id,  # type: ignore[attr-defined]
        topic=entry.topic,  # type: ignore[attr-defined]
        error_detail=entry.error_detail,  # type: ignore[attr-defined]
        status=entry.status,  # type: ignore[attr-defined]
        created_at=entry.created_at,  # type: ignore[attr-defined]
        resolved_at=entry.resolved_at,  # type: ignore[attr-defined]
        resolution_note=entry.resolution_note,  # type: ignore[attr-defined]
    )


class ListDLQEntriesUseCase:
    """List open DLQ entries with pagination.

    Read-only — uses ``ReadOnlyUnitOfWork`` to leverage the read replica (R27).
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, *, limit: int = 100, offset: int = 0) -> DLQListResult:
        async with self._uow:
            entries, total = await self._uow.dlq.list_open(limit=limit, offset=offset)
        return DLQListResult(
            entries=[_to_dto(e) for e in entries],
            count=total,
        )


class GetDLQEntryUseCase:
    """Get a single DLQ entry by ID.

    Read-only — uses ``ReadOnlyUnitOfWork`` to leverage the read replica (R27).
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, dlq_id: UUID) -> DLQEntryDTO | None:
        async with self._uow:
            entry = await self._uow.dlq.get_by_id(dlq_id)
        if entry is None:
            return None
        return _to_dto(entry)
