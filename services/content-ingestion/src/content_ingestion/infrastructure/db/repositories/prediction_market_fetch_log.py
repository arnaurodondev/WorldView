"""Repository for prediction_market_fetch_log table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
            text(
                "SELECT 1 FROM prediction_market_fetch_log "
                "WHERE market_id = :market_id AND snapshot_at = :snapshot_at LIMIT 1"
            ).bindparams(market_id=market_id, snapshot_at=snapshot_at)
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
    ) -> UUID | None:
        """Atomically insert a fetch log row; return the row UUID or None on conflict.

        F-308: Uses INSERT … ON CONFLICT (market_id, snapshot_at) DO NOTHING … RETURNING
        so concurrent workers cannot produce duplicate rows and no rollback is needed
        on duplicate detection.  Returns ``None`` when the row already exists.
        """
        row_id = common.ids.new_uuid7()
        stmt = (
            pg_insert(PredictionMarketFetchLogModel)
            .values(
                id=row_id,
                source_id=source_id,
                market_id=market_id,
                snapshot_at=snapshot_at,
                resolution_status=resolution_status,
                fetched_at=fetched_at,
            )
            .on_conflict_do_nothing(index_elements=["market_id", "snapshot_at"])
            .returning(PredictionMarketFetchLogModel.id)
        )
        result = await self._session.execute(stmt)
        returned = result.scalar_one_or_none()
        return returned if returned is not None else None
