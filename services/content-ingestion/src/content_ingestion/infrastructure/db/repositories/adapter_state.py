"""Repository for source_adapter_state table."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import select

import common.time
from content_ingestion.infrastructure.db.models import SourceAdapterStateModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class AdapterStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[SourceAdapterStateModel]:
        result = await self._session.execute(select(SourceAdapterStateModel))
        return list(result.scalars().all())

    async def get(self, source_id: UUID) -> SourceAdapterStateModel | None:
        result = await self._session.execute(
            select(SourceAdapterStateModel).where(SourceAdapterStateModel.source_id == source_id),
        )
        return cast("SourceAdapterStateModel | None", result.scalar_one_or_none())

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
    ) -> SourceAdapterStateModel:
        """Create or update the adapter state for a source."""
        row = await self.get(source_id)
        if row is None:
            row = SourceAdapterStateModel(source_id=source_id)
            self._session.add(row)

        if last_watermark is not None:
            row.last_watermark = last_watermark
        if last_cursor is not None:
            row.last_cursor = last_cursor
        if last_run_at is not None:
            row.last_run_at = last_run_at
        if next_run_at is not None:
            row.next_run_at = next_run_at
        if error_count is not None:
            row.error_count = error_count
        if last_error is not None:
            row.last_error = last_error

        row.updated_at = common.time.utc_now()
        await self._session.flush()
        return row

    async def reset_errors(self, source_id: UUID) -> None:
        """Reset error tracking after a successful run."""
        row = await self.get(source_id)
        if row is not None:
            row.error_count = 0
            row.last_error = None
            row.updated_at = common.time.utc_now()
            await self._session.flush()
