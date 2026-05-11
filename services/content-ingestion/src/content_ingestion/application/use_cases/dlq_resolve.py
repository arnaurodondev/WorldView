"""ResolveDLQEntryUseCase — mark a DLQ entry as resolved."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


class ResolveDLQEntryUseCase:
    """Mark a DLQ entry as resolved with a resolution note."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, dlq_id: UUID, *, note: str) -> bool:
        """Resolve. Returns False if DLQ entry not found."""
        async with self._uow:
            entry = await self._uow.dlq.get_by_id(dlq_id)
            if entry is None:
                return False
            await self._uow.dlq.mark_resolved(dlq_id, note=note)
            await self._uow.commit()

        logger.info("dlq_entry_resolved", dlq_id=str(dlq_id))
        return True
