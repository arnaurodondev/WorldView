"""SQLAlchemy implementation of BrokerageTransactionSyncErrorRepository.

Sync errors are append-only (immutable after creation) — no upsert needed.
``raw_transaction`` may contain sensitive financial data and MUST NEVER be
included in API responses or logs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from portfolio.application.ports.repositories import BrokerageTransactionSyncErrorRepository
from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
from portfolio.domain.enums import SyncErrorType
from portfolio.infrastructure.db.models.brokerage_sync_error import BrokerageTransactionSyncErrorModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyBrokerageTransactionSyncErrorRepository(BrokerageTransactionSyncErrorRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: BrokerageTransactionSyncErrorModel) -> BrokerageTransactionSyncError:
        return BrokerageTransactionSyncError(
            id=row.id,
            connection_id=row.connection_id,
            snaptrade_transaction_id=row.snaptrade_transaction_id,
            error_type=SyncErrorType(row.error_type),
            error_detail=row.error_detail,
            raw_transaction=row.raw_transaction,
            created_at=row.created_at,
        )

    async def save(self, error: BrokerageTransactionSyncError) -> None:
        row = BrokerageTransactionSyncErrorModel(
            id=error.id,
            connection_id=error.connection_id,
            snaptrade_transaction_id=error.snaptrade_transaction_id,
            error_type=str(error.error_type),
            error_detail=error.error_detail,
            raw_transaction=error.raw_transaction,
            created_at=error.created_at,
        )
        self._session.add(row)

    async def list_by_connection(
        self,
        connection_id: UUID,
        limit: int = 50,
    ) -> list[BrokerageTransactionSyncError]:
        result = await self._session.execute(
            select(BrokerageTransactionSyncErrorModel)
            .where(BrokerageTransactionSyncErrorModel.connection_id == connection_id)
            .order_by(BrokerageTransactionSyncErrorModel.created_at.desc())
            .limit(limit),
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def count_for_connection(self, connection_id: UUID) -> int:
        """Return total sync error count for a brokerage connection (W3 - FR-7).

        Uses a scalar COUNT(*) against the brokerage_sync_errors table filtered by
        connection_id. The new index added in Alembic migration 0026
        (``ix_brokerage_sync_errors_connection_id``) makes this O(1) on a bounded
        error set rather than a full table scan.

        Returns 0 (not None) when no errors exist -- the API layer propagates this
        as an integer field with a default of 0 so the frontend can do arithmetic
        without null-checking.
        """
        result = await self._session.execute(
            select(func.count())
            .select_from(BrokerageTransactionSyncErrorModel)
            .where(
                BrokerageTransactionSyncErrorModel.connection_id == connection_id,
            ),
        )
        return result.scalar_one() or 0
