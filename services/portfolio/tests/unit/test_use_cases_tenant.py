"""Unit tests for tenant use cases."""

from __future__ import annotations

import pytest
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase, GetTenantUseCase
from portfolio.domain.errors import EntityNotFoundError

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.unit


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.mark.asyncio
async def test_create_tenant_happy_path(uow: FakeUnitOfWork) -> None:
    """CreateTenantUseCase creates tenant + TenantCreated outbox event."""
    uc = CreateTenantUseCase()
    tenant = await uc.execute(CreateTenantCommand(name="ACME Corp"), uow)

    assert tenant.name == "ACME Corp"
    assert tenant.id is not None

    # Tenant saved to repo
    saved = await uow.tenants.get(tenant.id)
    assert saved is not None
    assert saved.name == "ACME Corp"

    # TenantCreated event in outbox
    events = uow.outbox.events_by_type("tenant.created")
    assert len(events) == 1
    assert events[0].payload["tenant_name"] == "ACME Corp"
    assert events[0].payload["tenant_id"] == str(tenant.id)


@pytest.mark.asyncio
async def test_create_tenant_generates_unique_id(uow: FakeUnitOfWork) -> None:
    """Two tenants get different IDs."""
    uc = CreateTenantUseCase()
    t1 = await uc.execute(CreateTenantCommand(name="Tenant A"), uow)
    t2 = await uc.execute(CreateTenantCommand(name="Tenant B"), uow)
    assert t1.id != t2.id


@pytest.mark.asyncio
async def test_get_tenant_returns_existing(uow: FakeUnitOfWork) -> None:
    """GetTenantUseCase returns the tenant when it exists."""
    uc_create = CreateTenantUseCase()
    tenant = await uc_create.execute(CreateTenantCommand(name="TestCo"), uow)

    uc_get = GetTenantUseCase()
    fetched = await uc_get.execute(tenant.id, uow)
    assert fetched.id == tenant.id
    assert fetched.name == "TestCo"


@pytest.mark.asyncio
async def test_get_tenant_not_found_raises(uow: FakeUnitOfWork) -> None:
    """GetTenantUseCase raises EntityNotFoundError when tenant missing."""
    from uuid import uuid4

    uc = GetTenantUseCase()
    with pytest.raises(EntityNotFoundError):
        await uc.execute(uuid4(), uow)
