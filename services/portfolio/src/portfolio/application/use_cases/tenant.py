"""Tenant use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.messaging.mapper import tenant_created_to_dict
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.domain.entities.tenant import Tenant
from portfolio.domain.errors import EntityNotFoundError
from portfolio.domain.events import TenantCreated

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class CreateTenantCommand:
    name: str


class CreateTenantUseCase:
    async def execute(self, cmd: CreateTenantCommand, uow: UnitOfWork) -> Tenant:
        tenant = Tenant(name=cmd.name, id=new_uuid())
        await uow.tenants.save(tenant)

        event = TenantCreated(tenant_id=tenant.id, tenant_name=tenant.name)
        from portfolio.application.ports.repositories import OutboxRecord

        record = OutboxRecord(
            id=new_uuid(),
            tenant_id=tenant.id,
            event_type=TenantCreated.EVENT_TYPE,
            topic=EVENT_TOPIC_MAP[TenantCreated.EVENT_TYPE],
            payload=tenant_created_to_dict(event),
            status="pending",
            attempt_count=0,
            lease_owner=None,
            lease_expires=None,
        )
        await uow.outbox.save(record)

        await uow.commit()
        logger.info("tenant_created", tenant_id=str(tenant.id), name=tenant.name)
        return tenant


class GetTenantUseCase:
    # R27: accepts ReadOnlyUnitOfWork so GET routes can pass ReadUoWDep; UnitOfWork
    # is a subtype so write-session callers remain compatible.
    async def execute(self, tenant_id: UUID, uow: ReadOnlyUnitOfWork) -> Tenant:
        tenant = await uow.tenants.get(tenant_id)
        if tenant is None:
            raise EntityNotFoundError(
                f"Tenant {tenant_id} not found",
                details={"tenant_id": str(tenant_id)},
            )
        return tenant
