"""Repository for fetch_logs table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

import common.ids
import common.time
from content_ingestion.infrastructure.db.models import FetchLogModel

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class FetchLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        url: str,
        url_hash: str,
        source_id: UUID,
        http_status: int,
        byte_size: int,
        fetched_at: datetime,
        published_at: datetime | None = None,
        is_backfill: bool = False,
        row_id: UUID | None = None,
    ) -> None:
        row = FetchLogModel(
            id=row_id or common.ids.new_uuid7(),
            source_id=source_id,
            url=url,
            url_hash=url_hash,
            http_status=http_status,
            byte_size=byte_size,
            fetched_at=fetched_at,
            published_at=published_at,
            is_backfill=is_backfill,
        )
        self._session.add(row)

    async def exists_by_url_hash(self, url_hash: str) -> bool:
        result = await self._session.execute(
            select(FetchLogModel.id).where(FetchLogModel.url_hash == url_hash).limit(1)
        )
        return result.scalar_one_or_none() is not None
