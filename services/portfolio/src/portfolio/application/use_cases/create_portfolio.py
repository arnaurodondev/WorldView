"""Create portfolio use case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.messaging.mapper import portfolio_created_to_dict
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.application.ports.repositories import OutboxRecord
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.errors import TenantInactiveError, UserInactiveError
from portfolio.domain.events import PortfolioCreated

if TYPE_CHECKING:
    from uuid import UUID

    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class CreatePortfolioCommand:
    tenant_id: UUID
    owner_id: UUID
    name: str
    currency: str = "USD"


class CreatePortfolioUseCase:
    async def execute(self, cmd: CreatePortfolioCommand, uow: UnitOfWork) -> Portfolio:
        tenant = await uow.tenants.get(cmd.tenant_id)
        if tenant is None or not tenant.is_active():
            raise TenantInactiveError(
                f"Tenant {cmd.tenant_id} is not active",
                tenant_id=cmd.tenant_id,
            )

        user = await uow.users.get(cmd.owner_id, cmd.tenant_id)
        if user is None or not user.is_active():
            raise UserInactiveError(
                f"User {cmd.owner_id} is not active",
                user_id=cmd.owner_id,
            )

        portfolio = Portfolio(
            id=new_uuid(),
            tenant_id=cmd.tenant_id,
            owner_id=cmd.owner_id,
            name=cmd.name,
            currency=cmd.currency,
        )
        await uow.portfolios.save(portfolio)

        # PortfolioCreated MUST be emitted (not commented out as in legacy)
        event = PortfolioCreated(
            tenant_id=portfolio.tenant_id,
            portfolio_id=portfolio.id,
            owner_id=portfolio.owner_id,
            name=portfolio.name,
            currency=portfolio.currency,
        )
        record = OutboxRecord(
            id=new_uuid(),
            tenant_id=portfolio.tenant_id,
            event_type=PortfolioCreated.EVENT_TYPE,
            topic=EVENT_TOPIC_MAP[PortfolioCreated.EVENT_TYPE],
            payload=portfolio_created_to_dict(event),
            status="pending",
            attempt_count=0,
            lease_owner=None,
            lease_expires=None,
        )
        await uow.outbox.save(record)

        await uow.commit()
        logger.info(
            "portfolio_created",
            tenant_id=str(portfolio.tenant_id),
            portfolio_id=str(portfolio.id),
        )
        return portfolio
