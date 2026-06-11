"""SQLAlchemy implementation of TransactionRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.ports.repositories import TransactionRepository
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import TradeSide, TransactionDirection, TransactionType
from portfolio.infrastructure.db.models.transaction import TransactionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)  # type: ignore[no-any-return]


class SqlAlchemyTransactionRepository(TransactionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: TransactionModel) -> Transaction:
        # 2026-06-10 (BP candidate, found during TWR work): PLAN-0108 added
        # ``trade_side`` to the entity + model + migration 0021 but this repo
        # was never updated — hydration dropped the column entirely. Because
        # ``Transaction.__post_init__`` REQUIRES trade_side for TRADE rows,
        # every read that touched a TRADE row raised ValueError → 500 on
        # realized-pnl / transactions page 2+ / TWR. Hydrate it properly and
        # INFER the side from direction for legacy rows persisted while
        # ``save()`` silently dropped the field (INFLOW=securities in=BUY,
        # OUTFLOW=securities out=SELL — the exact mapping used on the write
        # path in RecordTransactionUseCase).
        trade_side: TradeSide | None = None
        if row.transaction_type == TransactionType.TRADE:
            if row.trade_side:
                trade_side = TradeSide(row.trade_side)
            else:
                trade_side = TradeSide.BUY if row.direction == str(TransactionDirection.INFLOW) else TradeSide.SELL
                logger.warning(
                    "transaction_trade_side_inferred_from_direction",
                    transaction_id=str(row.id),
                    direction=row.direction,
                )
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
            # ``amount`` may be NULL on historical rows (column added in Alembic 0009
            # without backfill) or on rows where SnapTrade omitted the field.
            amount=row.amount,
            currency=row.currency,
            executed_at=row.executed_at,
            external_ref=row.external_ref,
            # P2-E: broker-supplied description (Alembic 0020). NULL on all rows
            # before the migration and when SnapTrade omits the field.
            description=row.description,
            trade_side=trade_side,
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

    async def list_by_portfolio_ids(
        self,
        portfolio_ids: list[UUID],
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        """Union of transactions across multiple portfolios for ROOT view.

        PLAN-0046 Wave 3 / T-46-3-03. Sorted ``executed_at DESC, created_at
        DESC`` so pagination is stable even when several transactions share
        the same trade date (very common for SnapTrade syncs).
        """
        if not portfolio_ids:
            return [], 0

        base_where = (
            TransactionModel.portfolio_id.in_(portfolio_ids),
            TransactionModel.tenant_id == tenant_id,
        )
        count_result = await self._session.execute(
            select(func.count()).select_from(TransactionModel).where(*base_where),
        )
        total: int = count_result.scalar_one()
        result = await self._session.execute(
            select(TransactionModel)
            .where(*base_where)
            .order_by(TransactionModel.executed_at.desc(), TransactionModel.created_at.desc())
            .limit(limit)
            .offset(offset),
        )
        return [self._to_entity(r) for r in result.scalars()], total

    async def list_all_for_portfolio_asc(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
    ) -> list[Transaction]:
        """Stream every transaction in chronological order.

        PLAN-0051 / T-A-1-04. The FIFO realised-P&L use case requires the
        complete history (including transactions for fully-closed positions),
        so we deliberately do NOT paginate. The unique index on
        ``(portfolio_id, executed_at)`` keeps this query cheap even for the
        thesis-scale data volumes we expect (a few thousand rows per
        portfolio). If we ever need to scale beyond that, the use case can
        switch to streaming via an async generator without changing the port
        contract.
        """
        result = await self._session.execute(
            select(TransactionModel)
            .where(
                TransactionModel.portfolio_id == portfolio_id,
                TransactionModel.tenant_id == tenant_id,
            )
            .order_by(TransactionModel.executed_at.asc(), TransactionModel.created_at.asc()),
        )
        return [self._to_entity(r) for r in result.scalars()]

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
                amount=transaction.amount,
                currency=transaction.currency,
                executed_at=transaction.executed_at,
                external_ref=transaction.external_ref,
                # P2-E (Wave G): broker-supplied human-readable description.
                # Nullable; historical rows + brokers that omit it stay NULL.
                description=transaction.description,
                # 2026-06-10: persist trade_side (PLAN-0108 follow-up — the
                # column existed since migration 0021 but save() never wrote
                # it, so TRADE rows landed with NULL and broke hydration).
                trade_side=str(transaction.trade_side) if transaction.trade_side is not None else None,
                created_at=transaction.created_at,
            )
            self._session.add(row)
