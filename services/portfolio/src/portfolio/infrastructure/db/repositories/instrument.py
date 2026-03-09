"""SQLAlchemy implementation of InstrumentRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from portfolio.application.ports.repositories import InstrumentRepository
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.infrastructure.db.models.instrument import InstrumentModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyInstrumentRepository(InstrumentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: InstrumentModel) -> InstrumentRef:
        return InstrumentRef(
            id=row.id,
            symbol=row.symbol,
            exchange=row.exchange,
            name=row.name,
            currency=row.currency,
            asset_class=row.asset_class,
            source_event_id=row.source_event_id,
            synced_at=row.synced_at,
        )

    async def get(self, instrument_id: UUID) -> InstrumentRef | None:
        result = await self._session.execute(select(InstrumentModel).where(InstrumentModel.id == instrument_id))
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def get_by_symbol_exchange(self, symbol: str, exchange: str) -> InstrumentRef | None:
        result = await self._session.execute(
            select(InstrumentModel).where(
                InstrumentModel.symbol == symbol,
                InstrumentModel.exchange == exchange,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_all(self) -> list[InstrumentRef]:
        result = await self._session.execute(select(InstrumentModel))
        return [self._to_entity(r) for r in result.scalars()]

    async def upsert(self, instrument: InstrumentRef) -> None:
        stmt = (
            pg_insert(InstrumentModel)
            .values(
                id=instrument.id,
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                name=instrument.name,
                currency=instrument.currency,
                asset_class=instrument.asset_class,
                source_event_id=instrument.source_event_id,
                synced_at=instrument.synced_at,
            )
            .on_conflict_do_update(
                index_elements=["symbol", "exchange"],
                set_={
                    "name": instrument.name,
                    "currency": instrument.currency,
                    "asset_class": instrument.asset_class,
                    "source_event_id": instrument.source_event_id,
                    "synced_at": instrument.synced_at,
                },
            )
        )
        await self._session.execute(stmt)
