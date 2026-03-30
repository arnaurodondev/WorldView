"""ListSourcesUseCase — list all configured polling sources with last-fetch metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass(frozen=True)
class SourceListItem:
    """Read-only DTO for a source with its last-fetch timestamp."""

    id: UUID
    name: str
    source_type: str
    enabled: bool
    last_fetch_at: datetime | None


class ListSourcesUseCase:
    """List all configured polling sources, enriched with adapter state metadata."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self) -> list[SourceListItem]:
        """Return all sources with their last-fetch timestamps."""
        async with self._uow:
            sources = await self._uow.sources.get_all()
            states = await self._uow.adapter_state.get_all()
            await self._uow.commit()

        state_map = {s.source_id: s for s in states}
        items = []
        for src in sources:
            state = state_map.get(src.id)
            items.append(
                SourceListItem(
                    id=src.id,
                    name=src.name,
                    source_type=src.source_type,
                    enabled=src.enabled,
                    last_fetch_at=state.last_run_at if state else None,
                )
            )
        logger.info("sources_listed", count=len(items))
        return items
