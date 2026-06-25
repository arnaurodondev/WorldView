"""PostgreSQL adapter for QuoteRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from market_data.application.ports.repositories import QuoteRepository
from market_data.domain.entities import Quote
from market_data.infrastructure.db.models.quotes import QuoteModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PgQuoteRepository(QuoteRepository):
    """SQLAlchemy-backed implementation of QuoteRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(row: QuoteModel) -> Quote:
        return Quote(
            instrument_id=row.instrument_id,
            bid=Decimal(str(row.bid)) if row.bid is not None else None,
            ask=Decimal(str(row.ask)) if row.ask is not None else None,
            last=Decimal(str(row.last)) if row.last is not None else None,
            volume=int(row.volume) if row.volume is not None else None,
            timestamp=row.timestamp or row.updated_at or datetime.now(tz=UTC),
            updated_at=row.updated_at or datetime.now(tz=UTC),
        )

    async def upsert(self, quote: Quote) -> Quote:
        stmt = (
            insert(QuoteModel)
            .values(
                instrument_id=quote.instrument_id,
                bid=quote.bid,
                ask=quote.ask,
                last=quote.last,
                volume=quote.volume,
                timestamp=quote.timestamp,
                updated_at=quote.updated_at,
            )
            .on_conflict_do_update(
                index_elements=["instrument_id"],
                set_={
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "last": quote.last,
                    "volume": quote.volume,
                    "timestamp": quote.timestamp,
                    "updated_at": quote.updated_at,
                },
            )
            .returning(QuoteModel)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one()
        return self._to_domain(row)

    async def upsert_if_newer(self, quote: Quote) -> bool:
        """Conditionally upsert: only overwrite when the incoming quote is newer.

        Used by the OHLCV 1m write-through (Option B): bars can be re-delivered
        out of order (Kafka rebalance, batch replays), so the UPDATE arm is
        guarded with ``WHERE quotes.timestamp < EXCLUDED.timestamp``.  A fresh
        row is always inserted; an existing row is only updated when the
        incoming timestamp is strictly newer.

        Returns:
            True if a row was inserted or updated, False if the existing row
            was newer (no-op).
        """
        insert_stmt = insert(QuoteModel).values(
            instrument_id=quote.instrument_id,
            bid=quote.bid,
            ask=quote.ask,
            last=quote.last,
            volume=quote.volume,
            timestamp=quote.timestamp,
            updated_at=quote.updated_at,
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["instrument_id"],
            set_={
                "bid": quote.bid,
                "ask": quote.ask,
                "last": quote.last,
                "volume": quote.volume,
                "timestamp": quote.timestamp,
                "updated_at": quote.updated_at,
            },
            # NULL-safe: quotes.timestamp is nullable; a NULL row must always
            # accept the incoming quote (NULL < x is NULL, which would skip).
            where=QuoteModel.timestamp.is_(None) | (QuoteModel.timestamp < insert_stmt.excluded.timestamp),
        ).returning(QuoteModel.instrument_id)
        result = await self._session.execute(stmt)
        # RETURNING yields a row only when the INSERT or the conditional
        # UPDATE actually fired; a guarded no-op returns zero rows.
        return result.scalar_one_or_none() is not None

    async def find_by_instrument(self, instrument_id: str) -> Quote | None:
        result = await self._session.execute(select(QuoteModel).where(QuoteModel.instrument_id == instrument_id))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def find_by_instruments(self, ids: list[str]) -> list[Quote]:
        result = await self._session.execute(select(QuoteModel).where(QuoteModel.instrument_id.in_(ids)))
        return [self._to_domain(row) for row in result.scalars().all()]
