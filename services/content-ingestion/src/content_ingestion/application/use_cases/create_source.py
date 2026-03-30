"""CreateSourceUseCase — create a new polling source."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass(frozen=True)
class CreateSourceResult:
    """DTO for the newly created source."""

    id: UUID
    name: str
    source_type: str
    enabled: bool


class CreateSourceUseCase:
    """Create a new polling source configuration.

    The scheduler process will automatically pick up new enabled sources
    on its next tick — no hot-add needed (R22).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        name: str,
        source_type: str,
        config: dict[str, Any],
        enabled: bool = True,
    ) -> CreateSourceResult:
        """Create the source and commit the transaction."""
        async with self._uow:
            source = await self._uow.sources.create(
                name=name,
                source_type=source_type,
                config=config,
                enabled=enabled,
            )
            await self._uow.commit()

        logger.info("source_created", source_id=str(source.id), name=name)
        return CreateSourceResult(
            id=source.id,
            name=source.name,
            source_type=source.source_type,
            enabled=source.enabled,
        )
