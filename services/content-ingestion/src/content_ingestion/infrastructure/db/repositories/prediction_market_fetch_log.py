"""Repository for prediction_market_fetch_log table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

import common.ids
from content_ingestion.infrastructure.db.models import PredictionMarketFetchLogModel

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class PredictionMarketFetchLogRepository:
    """SQLAlchemy implementation of PredictionMarketFetchLogPort."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists_by_market_snapshot(self, market_id: str, snapshot_at: datetime) -> bool:
        """Return True if a fetch log row exists for (market_id, snapshot_at)."""
        result = await self._session.execute(
            select(PredictionMarketFetchLogModel.id)
            .where(
                PredictionMarketFetchLogModel.market_id == market_id,
                PredictionMarketFetchLogModel.snapshot_at == snapshot_at,
            )
            .limit(1),
        )
        return result.scalar_one_or_none() is not None

    async def create_market_fetch_log(
        self,
        *,
        source_id: UUID | None,
        market_id: str,
        snapshot_at: datetime,
        resolution_status: str,
        fetched_at: datetime,
    ) -> UUID:
        """Insert a new prediction_market_fetch_log row and return its UUID."""
        row_id = common.ids.new_uuid7()
        row = PredictionMarketFetchLogModel(
            id=row_id,
            source_id=source_id,
            market_id=market_id,
            snapshot_at=snapshot_at,
            resolution_status=resolution_status,
            fetched_at=fetched_at,
        )
        self._session.add(row)
        return row_id
