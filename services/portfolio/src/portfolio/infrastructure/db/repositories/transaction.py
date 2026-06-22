"""SQLAlchemy implementation of TransactionRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Date, cast, func, select, text

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.ports.repositories import TransactionRepository
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import TradeSide, TransactionDirection, TransactionType
from portfolio.infrastructure.db.models.transaction import TransactionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from portfolio.domain.value_objects import TransactionFilter

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

    def _build_filter_clauses(self, tx_filter: TransactionFilter) -> list:  # type: ignore[type-arg]
        """Translate a ``TransactionFilter`` VO into SQLAlchemy WHERE clauses.

        PLAN-0114 / T-W2-02. Each non-None / non-empty field produces one
        WHERE predicate. ``from_date`` / ``to_date`` compare against
        ``(executed_at AT TIME ZONE 'UTC')::date`` (BP-180 guard — asyncpg rejects
        bare datetime comparisons with date parameters). The UTC-pinned cast is
        used (rather than a bare ``CAST(executed_at AS DATE)``) so it matches —
        and is served by — the IMMUTABLE functional index added in migration 0027
        (a plain timestamptz→date cast is NOT IMMUTABLE and cannot be indexed).
        All stored timestamps are UTC, so the date boundary is identical.
        ``ticker`` uses an EXISTS subquery on ``instruments`` with ILIKE so partial
        prefix match works case-insensitively without a JOIN that would change the
        row count.
        """
        clauses: list = []  # type: ignore[type-arg]

        # ``func.timezone('UTC', executed_at)`` renders as ``executed_at AT TIME ZONE
        # 'UTC'`` — an IMMUTABLE timestamptz→timestamp conversion; the outer
        # ``cast(..., Date)`` then yields the calendar date, matching the 0027 index.
        executed_date = cast(func.timezone("UTC", TransactionModel.executed_at), Date)
        if tx_filter.from_date is not None:
            clauses.append(executed_date >= tx_filter.from_date)
        if tx_filter.to_date is not None:
            clauses.append(executed_date <= tx_filter.to_date)
        if tx_filter.transaction_types:
            type_strings = [str(t) for t in tx_filter.transaction_types]
            clauses.append(TransactionModel.transaction_type.in_(type_strings))
        if tx_filter.ticker is not None:
            ticker_pattern = tx_filter.ticker.upper() + "%"
            clauses.append(
                text(  # type: ignore[arg-type]
                    "EXISTS (SELECT 1 FROM instruments "
                    "WHERE instruments.id = transactions.instrument_id "
                    "AND instruments.symbol ILIKE :ticker_pattern)"
                ).bindparams(ticker_pattern=ticker_pattern)
            )
        return clauses

    async def list_by_portfolio_filtered(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
        tx_filter: TransactionFilter,
    ) -> tuple[list[Transaction], int]:
        """Filtered paginated transactions for a single portfolio.

        PLAN-0114 / T-W2-02. Base WHERE predicates (portfolio_id + tenant_id)
        are ANDed with the filter clauses from ``_build_filter_clauses``.
        Pagination uses ``tx_filter.limit`` / ``tx_filter.offset``.
        """
        base_where = [
            TransactionModel.portfolio_id == portfolio_id,
            TransactionModel.tenant_id == tenant_id,
            *self._build_filter_clauses(tx_filter),
        ]
        count_result = await self._session.execute(
            select(func.count()).select_from(TransactionModel).where(*base_where),
        )
        total: int = count_result.scalar_one()
        result = await self._session.execute(
            select(TransactionModel)
            .where(*base_where)
            .order_by(TransactionModel.executed_at.desc(), TransactionModel.created_at.desc())
            .limit(tx_filter.limit)
            .offset(tx_filter.offset),
        )
        return [self._to_entity(r) for r in result.scalars()], total

    async def list_by_portfolio_ids_filtered(
        self,
        portfolio_ids: list[UUID],
        tenant_id: UUID,
        tx_filter: TransactionFilter,
    ) -> tuple[list[Transaction], int]:
        """Filtered paginated transactions across multiple portfolios (ROOT case).

        PLAN-0114 / T-W2-02. Same semantics as ``list_by_portfolio_ids`` but
        applies the ``TransactionFilter`` predicates. Empty ``portfolio_ids``
        returns ([], 0) immediately.
        """
        if not portfolio_ids:
            return [], 0

        base_where = [
            TransactionModel.portfolio_id.in_(portfolio_ids),
            TransactionModel.tenant_id == tenant_id,
            *self._build_filter_clauses(tx_filter),
        ]
        count_result = await self._session.execute(
            select(func.count()).select_from(TransactionModel).where(*base_where),
        )
        total: int = count_result.scalar_one()
        result = await self._session.execute(
            select(TransactionModel)
            .where(*base_where)
            .order_by(TransactionModel.executed_at.desc(), TransactionModel.created_at.desc())
            .limit(tx_filter.limit)
            .offset(tx_filter.offset),
        )
        return [self._to_entity(r) for r in result.scalars()], total

    async def list_all_for_portfolio_filtered(
        self,
        portfolio_id: UUID,
        tenant_id: UUID,
        tx_filter: TransactionFilter,
    ) -> list[Transaction]:
        """All matching transactions in chronological order — for CSV export.

        PLAN-0114 / T-W2-02. Used by ``ExportTransactionsUseCase`` which needs
        the complete filtered set ordered ASC for correct FIFO cost-basis replay.
        No pagination: streaming export pattern.
        """
        base_where = [
            TransactionModel.portfolio_id == portfolio_id,
            TransactionModel.tenant_id == tenant_id,
            *self._build_filter_clauses(tx_filter),
        ]
        result = await self._session.execute(
            select(TransactionModel)
            .where(*base_where)
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
