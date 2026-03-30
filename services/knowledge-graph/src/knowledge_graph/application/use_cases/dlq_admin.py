"""Use case for DLQ admin operations (list, inspect, resolve).

Depends only on the ``DLQRepositoryPort`` ABC — no infrastructure imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from knowledge_graph.application.ports.repositories import DLQEntryData, DLQRepositoryPort


class DLQAdminUseCase:
    """Application-layer use case for DLQ administration."""

    def __init__(self, repo: DLQRepositoryPort) -> None:
        self._repo = repo

    async def list_open(self, limit: int = 100, offset: int = 0) -> tuple[list[DLQEntryData], int]:
        """List open (failed) DLQ entries with total count."""
        return await self._repo.list_open(limit=limit, offset=offset)

    async def get_by_id(self, dlq_id: UUID) -> DLQEntryData | None:
        """Fetch a single DLQ entry by ID, or None if not found."""
        return await self._repo.get_by_id(dlq_id)

    async def mark_resolved(self, dlq_id: UUID, note: str | None) -> bool:
        """Mark a DLQ entry as resolved, then commit.

        Returns True if the entry was found and updated.
        """
        updated = await self._repo.mark_resolved(dlq_id, note)
        if updated:
            await self._repo.commit()
        return updated
