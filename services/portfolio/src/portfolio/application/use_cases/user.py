"""User use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.messaging.mapper import user_created_to_dict
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.application.ports.repositories import OutboxRecord
from portfolio.domain.entities.user import User
from portfolio.domain.errors import EntityAlreadyExistsError, EntityNotFoundError, TenantInactiveError
from portfolio.domain.events import UserCreated

if TYPE_CHECKING:
    from uuid import UUID

    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class CreateUserCommand:
    tenant_id: UUID
    email: str


class CreateUserUseCase:
    async def execute(self, cmd: CreateUserCommand, uow: UnitOfWork) -> User:
        tenant = await uow.tenants.get(cmd.tenant_id)
        if tenant is None or not tenant.is_active():
            raise TenantInactiveError(
                f"Tenant {cmd.tenant_id} is not active",
                tenant_id=cmd.tenant_id,
            )

        existing = await uow.users.get_by_email(cmd.email, cmd.tenant_id)
        if existing is not None:
            raise EntityAlreadyExistsError(
                f"User with email {cmd.email!r} already exists in tenant {cmd.tenant_id}",
            )

        user = User(tenant_id=cmd.tenant_id, email=cmd.email, id=new_uuid())
        await uow.users.save(user)

        event = UserCreated(tenant_id=user.tenant_id, user_id=user.id, email=user.email)
        record = OutboxRecord(
            id=new_uuid(),
            tenant_id=user.tenant_id,
            event_type=UserCreated.EVENT_TYPE,
            topic=EVENT_TOPIC_MAP[UserCreated.EVENT_TYPE],
            payload=user_created_to_dict(event),
            status="pending",
            attempt_count=0,
            lease_owner=None,
            lease_expires=None,
        )
        await uow.outbox.save(record)

        await uow.commit()
        logger.info("user_created", tenant_id=str(user.tenant_id), user_id=str(user.id))
        return user


class GetUserUseCase:
    async def execute(self, user_id: UUID, tenant_id: UUID, uow: UnitOfWork) -> User:
        user = await uow.users.get(user_id, tenant_id)
        if user is None:
            raise EntityNotFoundError(
                f"User {user_id} not found",
                details={"user_id": str(user_id)},
            )
        return user
