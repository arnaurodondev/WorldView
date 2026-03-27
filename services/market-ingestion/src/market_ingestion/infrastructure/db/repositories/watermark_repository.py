"""SQLAlchemy implementation of WatermarkRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from common.ids import new_ulid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.application.ports.repositories import WatermarkRepository
from market_ingestion.domain.entities.watermark import Watermark
from market_ingestion.domain.enums import BackfillStatus
from market_ingestion.infrastructure.db.models.watermark import WatermarkModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _to_domain(row: WatermarkModel) -> Watermark:
    return Watermark(
        id=row.id,
        provider=row.provider,
        dataset_type=row.dataset_type,
        variant=row.dataset_variant,
        symbol=row.symbol,
        exchange=row.exchange,
        timeframe=row.timeframe,
        current_bar_ts=row.last_success_bar_ts,
        content_hash=row.last_success_sha256,
        backfill_status=BackfillStatus(row.backfill_phase),
        updated_at=row.updated_at,
    )


class SqlaWatermarkRepository(WatermarkRepository):
    """SQLAlchemy-backed WatermarkRepository."""

    def __init__(self, write_session: AsyncSession, read_session: AsyncSession) -> None:
        self._w = write_session
        self._r = read_session

    async def get(
        self,
        *,
        provider: str,
        dataset_type: str,
        symbol: str,
        exchange: str | None = None,
        timeframe: str | None = None,
        variant: str | None = None,
    ) -> Watermark | None:
        stmt = (
            select(WatermarkModel)
            .where(
                WatermarkModel.provider == provider,
                WatermarkModel.dataset_type == dataset_type,
                WatermarkModel.dataset_variant == variant,
                WatermarkModel.symbol == symbol,
                WatermarkModel.exchange == exchange,
                WatermarkModel.timeframe == timeframe,
            )
            .limit(1)
        )
        row = (await self._r.execute(stmt)).scalar_one_or_none()
        return _to_domain(row) if row else None

    async def get_or_create(
        self,
        *,
        provider: str,
        dataset_type: str,
        symbol: str,
        exchange: str | None = None,
        timeframe: str | None = None,
        variant: str | None = None,
    ) -> Watermark:
        now = utc_now()
        new_id = new_ulid()
        stmt = (
            pg_insert(WatermarkModel)
            .values(
                id=new_id,
                provider=provider,
                dataset_type=dataset_type,
                dataset_variant=variant,
                symbol=symbol,
                exchange=exchange,
                timeframe=timeframe,
                backfill_phase=BackfillStatus.PENDING.value,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "provider",
                    "dataset_type",
                    "dataset_variant",
                    "symbol",
                    "exchange",
                    "timeframe",
                ]
            )
        )
        await self._w.execute(stmt)
        # SELECT the row (may have been inserted by us or already existed)
        existing = await self.get(
            provider=provider,
            dataset_type=dataset_type,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            variant=variant,
        )
        if existing:
            return existing
        # Fallback: build a transient domain object using the ID we generated
        return Watermark(
            id=new_id,
            provider=provider,
            dataset_type=dataset_type,
            variant=variant,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            updated_at=now,
        )

    async def get_for_update(
        self,
        *,
        provider: str,
        dataset_type: str,
        symbol: str,
        exchange: str | None = None,
        timeframe: str | None = None,
        variant: str | None = None,
    ) -> Watermark | None:
        """Load watermark row with a row-level lock. Must be called inside an open transaction."""
        stmt = (
            select(WatermarkModel)
            .where(
                WatermarkModel.provider == provider,
                WatermarkModel.dataset_type == dataset_type,
                WatermarkModel.dataset_variant == variant,
                WatermarkModel.symbol == symbol,
                WatermarkModel.exchange == exchange,
                WatermarkModel.timeframe == timeframe,
            )
            .limit(1)
            .with_for_update()
        )
        row = (await self._w.execute(stmt)).scalar_one_or_none()
        return _to_domain(row) if row else None

    async def save(self, watermark: Watermark) -> None:
        from sqlalchemy import update

        now = utc_now()
        stmt = (
            update(WatermarkModel)
            .where(WatermarkModel.id == watermark.id)
            .values(
                last_success_bar_ts=watermark.current_bar_ts,
                last_success_sha256=watermark.content_hash,
                backfill_phase=watermark.backfill_status.value,
                updated_at=now,
            )
        )
        await self._w.execute(stmt)

    async def list_by_provider(
        self,
        provider: str,
        dataset_type: str | None = None,
    ) -> list[Watermark]:
        filters = [WatermarkModel.provider == provider]
        if dataset_type is not None:
            filters.append(WatermarkModel.dataset_type == dataset_type)
        stmt = select(WatermarkModel).where(*filters)
        rows = (await self._r.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows]
