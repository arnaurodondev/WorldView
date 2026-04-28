"""SQLAlchemy implementation of HoldingRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from portfolio.application.ports.repositories import HoldingRepository
from portfolio.application.use_cases.read_models import EnrichedHolding
from portfolio.domain.entities.holding import Holding
from portfolio.infrastructure.db.models.holding import HoldingModel
from portfolio.infrastructure.db.models.instrument import InstrumentModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyHoldingRepository(HoldingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: HoldingModel) -> Holding:
        return Holding(
            id=row.id,
            portfolio_id=row.portfolio_id,
            instrument_id=row.instrument_id,
            tenant_id=row.tenant_id,
            quantity=row.quantity,
            average_cost=row.average_cost,
            currency=row.currency,
            updated_at=row.updated_at,
        )

    async def get(self, portfolio_id: UUID, instrument_id: UUID) -> Holding | None:
        result = await self._session.execute(
            select(HoldingModel).where(
                HoldingModel.portfolio_id == portfolio_id,
                HoldingModel.instrument_id == instrument_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_portfolio(self, portfolio_id: UUID) -> list[Holding]:
        result = await self._session.execute(select(HoldingModel).where(HoldingModel.portfolio_id == portfolio_id))
        return [self._to_entity(r) for r in result.scalars()]

    async def list_by_portfolio_enriched(self, portfolio_id: UUID) -> list[EnrichedHolding]:
        """Return holdings with ticker/name/entity_id from the instruments table.

        WHY LEFT OUTER JOIN: a holding may reference an instrument_id that has not
        yet been synced from S3 (race condition between SnapTrade sync and instrument
        consumer). LEFT JOIN ensures all holdings are returned even without an instrument
        record — the enrichment fields default to None and the frontend degrades gracefully.
        """
        stmt = (
            select(HoldingModel, InstrumentModel.symbol, InstrumentModel.name, InstrumentModel.entity_id)
            .outerjoin(InstrumentModel, HoldingModel.instrument_id == InstrumentModel.id)
            .where(HoldingModel.portfolio_id == portfolio_id)
        )
        result = await self._session.execute(stmt)
        enriched: list[EnrichedHolding] = []
        for holding_row, symbol, name, entity_id in result.tuples():
            enriched.append(
                EnrichedHolding(
                    holding=self._to_entity(holding_row),
                    ticker=symbol,
                    name=name,
                    entity_id=entity_id,
                )
            )
        return enriched

    async def save(self, holding: Holding) -> None:
        row = await self._session.get(HoldingModel, holding.id)
        if row is None:
            row = HoldingModel(
                id=holding.id,
                portfolio_id=holding.portfolio_id,
                instrument_id=holding.instrument_id,
                tenant_id=holding.tenant_id,
                quantity=holding.quantity,
                average_cost=holding.average_cost,
                currency=holding.currency,
                updated_at=holding.updated_at,
            )
            self._session.add(row)
        else:
            row.quantity = holding.quantity
            row.average_cost = holding.average_cost
            row.updated_at = holding.updated_at
