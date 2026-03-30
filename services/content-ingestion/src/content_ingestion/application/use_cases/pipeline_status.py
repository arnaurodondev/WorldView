"""GetPipelineStatusUseCase — pipeline ingestion status summary."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime

    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass(frozen=True)
class SourceStatusInfo:
    """Per-source status detail."""

    name: str
    last_fetch_at: datetime | None = None
    articles_fetched_24h: int = 0
    errors_24h: int = 0


@dataclass(frozen=True)
class PipelineStatus:
    """Pipeline ingestion status summary."""

    sources: list[SourceStatusInfo] = field(default_factory=list)
    outbox_pending: int = 0
    dlq_count: int = 0


class GetPipelineStatusUseCase:
    """Aggregate pipeline status from multiple repositories."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self) -> PipelineStatus:
        """Build and return the pipeline status summary."""
        cutoff = utc_now() - dt.timedelta(hours=24)

        async with self._uow:
            sources = await self._uow.sources.get_all()
            states = await self._uow.adapter_state.get_all()
            state_map = {s.source_id: s for s in states}

            details: list[SourceStatusInfo] = []
            for src in sources:
                state = state_map.get(src.id)
                fetched_24h = await self._uow.fetch_logs.count_by_source_since(src.id, cutoff)
                details.append(
                    SourceStatusInfo(
                        name=src.name,
                        last_fetch_at=state.last_run_at if state else None,
                        articles_fetched_24h=fetched_24h,
                        errors_24h=state.error_count if state else 0,
                    )
                )

            outbox_pending = await self._uow.outbox.count_pending()
            dlq_count = await self._uow.dlq.count_failed()
            await self._uow.commit()

        return PipelineStatus(
            sources=details,
            outbox_pending=outbox_pending,
            dlq_count=dlq_count,
        )
