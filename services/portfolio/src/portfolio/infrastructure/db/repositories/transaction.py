"""SQLAlchemy implementation of TransactionRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from portfolio.application.ports.repositories import TransactionRepository
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import TransactionDirection, TransactionType
from portfolio.infrastructure.db.models.transaction import TransactionModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyTransactionRepository(TransactionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: TransactionModel) -> Transaction:
        return Transaction(
            id=row.id,
            tenant_id=row.tenant_id,
            portfolio_id=row.portfolio_id,
            instrument_id=row.instrument_id,
            transaction_type=TransactionType(row.transaction_type),
            direction=TransactionDirection(row.direction),
            quantity=row.quantity,
            price=row.price,
            fees=row.fees,
            currency=row.currency,
            executed_at=row.executed_at,
            external_ref=row.external_ref,
            created_at=row.created_at,
        )

    async def get(self, transaction_id: UUID, tenant_id: UUID) -> Transaction | None:
        result = await self._session.execute(
            select(TransactionModel).where(
                TransactionModel.id == transaction_id,
                TransactionModel.tenant_id == tenant_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def find_by_external_ref(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
        external_ref: str,
    ) -> Transaction | None:
        result = await self._session.execute(
            select(TransactionModel).where(
                TransactionModel.portfolio_id == portfolio_id,
                TransactionModel.tenant_id == tenant_id,
                TransactionModel.external_ref == external_ref,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_portfolio(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        base_where = (
            TransactionModel.portfolio_id == portfolio_id,
            TransactionModel.tenant_id == tenant_id,
        )
        count_result = await self._session.execute(
            select(func.count()).select_from(TransactionModel).where(*base_where),
        )
        total: int = count_result.scalar_one()
        result = await self._session.execute(select(TransactionModel).where(*base_where).limit(limit).offset(offset))
        return [self._to_entity(r) for r in result.scalars()], total

    async def save(self, transaction: Transaction) -> None:
        row = await self._session.get(TransactionModel, transaction.id)
        if row is None:
            row = TransactionModel(
                id=transaction.id,
                tenant_id=transaction.tenant_id,
                portfolio_id=transaction.portfolio_id,
                instrument_id=transaction.instrument_id,
                transaction_type=str(transaction.transaction_type),
                direction=str(transaction.direction),
                quantity=transaction.quantity,
                price=transaction.price,
                fees=transaction.fees,
                currency=transaction.currency,
                executed_at=transaction.executed_at,
                external_ref=transaction.external_ref,
                created_at=transaction.created_at,
            )
            self._session.add(row)
