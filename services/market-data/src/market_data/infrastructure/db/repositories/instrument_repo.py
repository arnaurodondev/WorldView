"""PostgreSQL adapter for InstrumentRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from market_data.application.ports.repositories import InstrumentRepository
from market_data.domain.entities import Instrument
from market_data.domain.value_objects import InstrumentFlags
from market_data.infrastructure.db.models.instruments import InstrumentModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PgInstrumentRepository(InstrumentRepository):
    """SQLAlchemy-backed implementation of InstrumentRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── mapping ────────────────────────────────────────────────────────────────

    @staticmethod
    def _to_domain(row: InstrumentModel) -> Instrument:
        return Instrument(
            id=row.id,
            security_id=row.security_id,
            symbol=row.symbol,
            exchange=row.exchange,
            flags=InstrumentFlags(
                has_ohlcv=row.has_ohlcv,
                has_quotes=row.has_quotes,
                has_fundamentals=row.has_fundamentals,
            ),
            is_active=True,
            created_at=row.created_at,
            name=row.name,
            isin=row.isin,
            sector=row.sector,
            industry=row.industry,
            country=row.country,
            currency_code=row.currency_code,
        )

    # ── queries ────────────────────────────────────────────────────────────────

    async def find_by_symbol_exchange(self, symbol: str, exchange: str) -> Instrument | None:
        result = await self._session.execute(
            select(InstrumentModel).where(
                InstrumentModel.symbol == symbol,
                InstrumentModel.exchange == exchange,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def find_by_id(self, id: str) -> Instrument | None:  # noqa: A002
        result = await self._session.execute(select(InstrumentModel).where(InstrumentModel.id == id))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def search(
        self,
        query: str,
        *,
        has_ohlcv: bool | None = None,
        has_quotes: bool | None = None,
        has_fundamentals: bool | None = None,
        exchange: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Instrument]:
        from sqlalchemy import and_

        conditions = []
        if query:
            pattern = f"%{query}%"
            conditions.append(
                or_(
                    InstrumentModel.symbol.ilike(pattern),
                    InstrumentModel.exchange.ilike(pattern),
                )
            )
        if has_ohlcv is not None:
            conditions.append(InstrumentModel.has_ohlcv == has_ohlcv)
        if has_quotes is not None:
            conditions.append(InstrumentModel.has_quotes == has_quotes)
        if has_fundamentals is not None:
            conditions.append(InstrumentModel.has_fundamentals == has_fundamentals)
        if exchange is not None:
            conditions.append(InstrumentModel.exchange == exchange)

        stmt = select(InstrumentModel)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.offset(offset).limit(limit)

        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def count(
        self,
        query: str = "",
        *,
        has_ohlcv: bool | None = None,
        has_quotes: bool | None = None,
        has_fundamentals: bool | None = None,
        exchange: str | None = None,
    ) -> int:
        from sqlalchemy import and_, func

        conditions = []
        if query:
            pattern = f"%{query}%"
            conditions.append(
                or_(
                    InstrumentModel.symbol.ilike(pattern),
                    InstrumentModel.exchange.ilike(pattern),
                )
            )
        if has_ohlcv is not None:
            conditions.append(InstrumentModel.has_ohlcv == has_ohlcv)
        if has_quotes is not None:
            conditions.append(InstrumentModel.has_quotes == has_quotes)
        if has_fundamentals is not None:
            conditions.append(InstrumentModel.has_fundamentals == has_fundamentals)
        if exchange is not None:
            conditions.append(InstrumentModel.exchange == exchange)

        stmt = select(func.count()).select_from(InstrumentModel)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        result = await self._session.execute(stmt)
        return cast(int, result.scalar_one())

    async def upsert(self, instrument: Instrument) -> Instrument:
        stmt = (
            insert(InstrumentModel)
            .values(
                id=instrument.id,
                security_id=instrument.security_id,
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                has_ohlcv=instrument.flags.has_ohlcv,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=instrument.flags.has_fundamentals,
            )
            .on_conflict_do_update(
                constraint="uq_instruments_symbol_exchange",
                set_={
                    "security_id": instrument.security_id,
                    "has_ohlcv": instrument.flags.has_ohlcv,
                    "has_quotes": instrument.flags.has_quotes,
                    "has_fundamentals": instrument.flags.has_fundamentals,
                },
            )
            .returning(InstrumentModel)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one()
        return self._to_domain(row)

    async def update_flags(self, id: str, flags: InstrumentFlags) -> None:  # noqa: A002
        from sqlalchemy import update

        await self._session.execute(
            update(InstrumentModel)
            .where(InstrumentModel.id == id)
            .values(
                has_ohlcv=flags.has_ohlcv,
                has_quotes=flags.has_quotes,
                has_fundamentals=flags.has_fundamentals,
            )
        )

    async def update_metadata(self, id: str, metadata: dict[str, str | None]) -> None:  # noqa: A002
        """Update instrument metadata fields, ignoring None-valued keys."""
        from sqlalchemy import update

        # Filter out None values — only update fields that have actual data
        updates = {k: v for k, v in metadata.items() if v is not None}
        if not updates:
            return
        await self._session.execute(update(InstrumentModel).where(InstrumentModel.id == id).values(**updates))
