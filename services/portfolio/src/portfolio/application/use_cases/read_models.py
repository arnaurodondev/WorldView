"""Read model use cases for holdings and transactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

if TYPE_CHECKING:
    from uuid import UUID

    from portfolio.application.ports.unit_of_work import UnitOfWork
    from portfolio.domain.entities import Holding, Transaction

logger = get_logger(__name__)  # type: ignore[no-any-return]


class GetHoldingsUseCase:
    async def execute(self, portfolio_id: UUID, owner_id: UUID, tenant_id: UUID, uow: UnitOfWork) -> list[Holding]:
        portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
        if portfolio.owner_id != owner_id:
            raise AuthorizationError("Not authorized to view this portfolio's holdings")
        return await uow.holdings.list_by_portfolio(portfolio_id)


class ListTransactionsUseCase:
    async def execute(
        self,
        portfolio_id: UUID,
        owner_id: UUID,
        tenant_id: UUID,
        uow: UnitOfWork,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
        if portfolio.owner_id != owner_id:
            raise AuthorizationError("Not authorized to view this portfolio's transactions")
        return await uow.transactions.list_by_portfolio(portfolio_id, tenant_id, limit=limit, offset=offset)
