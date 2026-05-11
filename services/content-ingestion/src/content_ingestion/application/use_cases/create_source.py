"""CreateSourceUseCase — create a new polling source."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass(frozen=True)
class CreateSourceResult:
    """DTO for the newly created (or already-existing) source.

    PLAN-0055 B-1: ``was_created`` is False when the underlying repository found
    an existing row with the same ``(source_type, config_hash)``. Callers can
    surface this distinction to operators who expected a fresh insert.
    """

    id: UUID
    name: str
    source_type: str
    enabled: bool
    was_created: bool


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
        """Create the source and commit the transaction.

        Idempotent (PLAN-0055 B-1): if a source with the same
        ``(source_type, config_hash)`` already exists, the existing row is
        returned with ``was_created=False`` instead of raising.
        """
        async with self._uow:
            source, was_created = await self._uow.sources.create(
                name=name,
                source_type=source_type,
                config=config,
                enabled=enabled,
            )
            await self._uow.commit()

        if was_created:
            logger.info("source_created", source_id=str(source.id), name=name)
        else:
            logger.info(
                "source_create_idempotent_hit",
                source_id=str(source.id),
                name=name,
                source_type=source_type,
            )
        return CreateSourceResult(
            id=source.id,
            name=source.name,
            source_type=source.source_type,
            enabled=source.enabled,
            was_created=was_created,
        )
