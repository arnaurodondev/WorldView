"""Portfolio operation use cases: get, list, rename, archive."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.messaging.mapper import portfolio_archived_to_dict, portfolio_renamed_to_dict
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.application.ports.repositories import OutboxRecord
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError
from portfolio.domain.events import PortfolioArchived, PortfolioRenamed

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork
    from portfolio.domain.entities import Portfolio

logger = get_logger(__name__)  # type: ignore[no-any-return]


class GetPortfolioUseCase:
    async def execute(self, portfolio_id: UUID, owner_id: UUID, tenant_id: UUID, uow: ReadOnlyUnitOfWork) -> Portfolio:
        portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
        if portfolio.owner_id != owner_id:
            raise AuthorizationError("Not authorized to access this portfolio")
        return portfolio


class ListPortfoliosUseCase:
    async def execute(
        self,
        owner_id: UUID,
        tenant_id: UUID,
        uow: ReadOnlyUnitOfWork,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Portfolio], int]:
        return await uow.portfolios.list_by_owner(owner_id, tenant_id, limit=limit, offset=offset)


class ArchivePortfolioUseCase:
    async def execute(self, portfolio_id: UUID, owner_id: UUID, tenant_id: UUID, uow: UnitOfWork) -> None:
        portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
        if portfolio.owner_id != owner_id:
            raise AuthorizationError("Not authorized to archive this portfolio")

        portfolio.archive()
        await uow.portfolios.save(portfolio)

        event = PortfolioArchived(
            tenant_id=portfolio.tenant_id,
            portfolio_id=portfolio.id,
        )
        record = OutboxRecord(
            id=new_uuid(),
            tenant_id=portfolio.tenant_id,
            event_type=PortfolioArchived.EVENT_TYPE,
            topic=EVENT_TOPIC_MAP[PortfolioArchived.EVENT_TYPE],
            payload=portfolio_archived_to_dict(event),
            status="pending",
            attempt_count=0,
            lease_owner=None,
            lease_expires=None,
        )
        await uow.outbox.save(record)
        await uow.commit()
        logger.info("portfolio_archived", portfolio_id=str(portfolio_id))


@dataclass
class RenamePortfolioCommand:
    portfolio_id: UUID
    owner_id: UUID
    tenant_id: UUID
    new_name: str


class RenamePortfolioUseCase:
    async def execute(self, cmd: RenamePortfolioCommand, uow: UnitOfWork) -> Portfolio:
        portfolio = await uow.portfolios.get(cmd.portfolio_id, cmd.tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {cmd.portfolio_id} not found")
        if portfolio.owner_id != cmd.owner_id:
            raise AuthorizationError("Not authorized to rename this portfolio")

        old_name = portfolio.name
        portfolio.rename(cmd.new_name)  # raises PortfolioArchivedError if archived
        await uow.portfolios.save(portfolio)

        event = PortfolioRenamed(
            tenant_id=portfolio.tenant_id,
            portfolio_id=portfolio.id,
            old_name=old_name,
            new_name=cmd.new_name,
        )
        record = OutboxRecord(
            id=new_uuid(),
            tenant_id=portfolio.tenant_id,
            event_type=PortfolioRenamed.EVENT_TYPE,
            topic=EVENT_TOPIC_MAP[PortfolioRenamed.EVENT_TYPE],
            payload=portfolio_renamed_to_dict(event),
            status="pending",
            attempt_count=0,
            lease_owner=None,
            lease_expires=None,
        )
        await uow.outbox.save(record)
        await uow.commit()
        logger.info(
            "portfolio_renamed",
            portfolio_id=str(cmd.portfolio_id),
            old_name=old_name,
            new_name=cmd.new_name,
        )
        return portfolio
