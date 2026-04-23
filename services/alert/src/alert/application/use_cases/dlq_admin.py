"""Use case for DLQ admin operations (list, inspect, resolve).

Depends only on the ``DLQRepositoryPort`` ABC — no infrastructure imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from alert.application.ports.repositories import DLQRepositoryPort
    from alert.domain.entities import DeadLetterEntry


class DLQAdminUseCase:
    """Application-layer use case for DLQ administration."""

    def __init__(self, repo: DLQRepositoryPort) -> None:
        self._repo = repo

    async def list_failed(self, limit: int = 50, offset: int = 0) -> list[DeadLetterEntry]:
        """List failed DLQ entries."""
        return await self._repo.list_failed(limit=limit, offset=offset)

    async def count_failed(self) -> int:
        """Return total count of failed DLQ entries."""
        return await self._repo.count_failed()

    async def get_by_id(self, dlq_id: UUID) -> DeadLetterEntry | None:
        """Fetch a single DLQ entry by ID, or None if not found."""
        return await self._repo.get_by_id(dlq_id)

    async def resolve(self, dlq_id: UUID, resolution_note: str) -> bool:
        """Mark a DLQ entry as resolved, then commit.

        Returns True if the entry was found and updated, False otherwise.
        """
        updated = await self._repo.resolve(dlq_id, resolution_note=resolution_note)
        if updated:
            await self._repo.commit()
        return updated
