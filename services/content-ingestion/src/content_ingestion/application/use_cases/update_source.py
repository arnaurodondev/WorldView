"""UpdateSourceUseCase — update an existing polling source."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass(frozen=True)
class UpdateSourceResult:
    """DTO for the updated source."""

    id: UUID
    name: str
    source_type: str
    enabled: bool


class UpdateSourceUseCase:
    """Update a polling source's mutable fields (name, enabled, config).

    Enabling/disabling a source takes effect on the next scheduler tick (R22).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, source_id: UUID, **updates: Any) -> UpdateSourceResult | None:
        """Update the source. Returns None if source not found."""
        async with self._uow:
            existing = await self._uow.sources.get_by_id(source_id)
            if existing is None:
                return None

            if updates:
                source = await self._uow.sources.update(source_id, **updates)
            else:
                source = existing
            await self._uow.commit()

        logger.info("source_updated", source_id=str(source_id), fields=list(updates.keys()))
        return UpdateSourceResult(
            id=source.id,
            name=source.name,
            source_type=source.source_type,
            enabled=source.enabled,
        )
