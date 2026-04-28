"""Read model use cases for holdings and transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.enums import PortfolioKind
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork
    from portfolio.domain.entities import Holding, Transaction

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class EnrichedHolding:
    """Holding with instrument metadata joined from the instruments table.

    WHY a separate DTO (not modifying domain Holding entity): the instruments
    JOIN is an infrastructure concern — the Holding domain entity must not carry
    optional ticker/name fields that only exist when the instrument ref is present.
    This DTO is purely application-layer transport.
    """

    holding: Holding
    ticker: str | None
    name: str | None
    entity_id: UUID | None


class GetHoldingsUseCase:
    async def execute(
        self,
        portfolio_id: UUID,
        owner_id: UUID,
        tenant_id: UUID,
        uow: ReadOnlyUnitOfWork,
    ) -> list[EnrichedHolding]:
        portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
        if portfolio.owner_id != owner_id:
            raise AuthorizationError("Not authorized to view this portfolio's holdings")

        # PLAN-0046 Wave 3 / T-46-3-03: ROOT portfolios aggregate the user's
        # other portfolios. Replace the WHERE portfolio_id = X predicate with
        # WHERE portfolio_id IN (sub-portfolios), then collapse by instrument_id
        # with quantity sum + qty-weighted average cost.
        if portfolio.kind == PortfolioKind.ROOT:
            sub_ids = await uow.portfolios.list_non_root_active_ids_by_owner(owner_id, tenant_id)
            return await uow.holdings.list_by_portfolio_ids_aggregated_enriched(sub_ids)

        return await uow.holdings.list_by_portfolio_enriched(portfolio_id)


class ListTransactionsUseCase:
    async def execute(
        self,
        portfolio_id: UUID,
        owner_id: UUID,
        tenant_id: UUID,
        uow: ReadOnlyUnitOfWork,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
        if portfolio.owner_id != owner_id:
            raise AuthorizationError("Not authorized to view this portfolio's transactions")

        # PLAN-0046 Wave 3 / T-46-3-03: ROOT portfolios show the union of
        # transactions across the user's sub-portfolios, sorted newest-first.
        # No aggregation — every original transaction row is preserved.
        if portfolio.kind == PortfolioKind.ROOT:
            sub_ids = await uow.portfolios.list_non_root_active_ids_by_owner(owner_id, tenant_id)
            return await uow.transactions.list_by_portfolio_ids(
                sub_ids,
                tenant_id,
                limit=limit,
                offset=offset,
            )

        return await uow.transactions.list_by_portfolio(portfolio_id, tenant_id, limit=limit, offset=offset)
