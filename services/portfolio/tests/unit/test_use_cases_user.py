"""Unit tests for user use cases."""

from __future__ import annotations

from uuid import uuid4

import pytest
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase
from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase, GetUserUseCase
from portfolio.domain.entities.tenant import Tenant
from portfolio.domain.enums import TenantStatus
from portfolio.domain.errors import EntityAlreadyExistsError, EntityNotFoundError, TenantInactiveError

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.unit


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
async def active_tenant(uow: FakeUnitOfWork) -> Tenant:
    uc = CreateTenantUseCase()
    return await uc.execute(CreateTenantCommand(name="ACME"), uow)


@pytest.mark.asyncio
async def test_create_user_happy_path(uow: FakeUnitOfWork, active_tenant: Tenant) -> None:
    """CreateUserUseCase creates user + UserCreated outbox event."""
    uc = CreateUserUseCase()
    user = await uc.execute(CreateUserCommand(tenant_id=active_tenant.id, email="alice@acme.com"), uow)

    assert user.email == "alice@acme.com"
    assert user.tenant_id == active_tenant.id

    events = uow.outbox.events_by_type("user.created")
    assert len(events) == 1
    assert events[0].payload["email"] == "alice@acme.com"


@pytest.mark.asyncio
async def test_create_user_inactive_tenant_raises(uow: FakeUnitOfWork) -> None:
    """CreateUserUseCase raises TenantInactiveError when tenant is not active."""
    inactive_tenant = Tenant(id=uuid4(), name="InactiveCo", status=TenantStatus.SUSPENDED)
    uow.seed_tenant(inactive_tenant)

    uc = CreateUserUseCase()
    with pytest.raises(TenantInactiveError):
        await uc.execute(CreateUserCommand(tenant_id=inactive_tenant.id, email="bob@test.com"), uow)


@pytest.mark.asyncio
async def test_create_user_missing_tenant_raises(uow: FakeUnitOfWork) -> None:
    """CreateUserUseCase raises TenantInactiveError when tenant not found."""
    uc = CreateUserUseCase()
    with pytest.raises(TenantInactiveError):
        await uc.execute(CreateUserCommand(tenant_id=uuid4(), email="ghost@test.com"), uow)


@pytest.mark.asyncio
async def test_create_user_duplicate_email_raises(uow: FakeUnitOfWork, active_tenant: Tenant) -> None:
    """CreateUserUseCase raises EntityAlreadyExistsError on duplicate email."""
    uc = CreateUserUseCase()
    await uc.execute(CreateUserCommand(tenant_id=active_tenant.id, email="dup@acme.com"), uow)

    with pytest.raises(EntityAlreadyExistsError):
        await uc.execute(CreateUserCommand(tenant_id=active_tenant.id, email="dup@acme.com"), uow)


@pytest.mark.asyncio
async def test_get_user_not_found_raises(uow: FakeUnitOfWork, active_tenant: Tenant) -> None:
    """GetUserUseCase raises EntityNotFoundError when user missing."""
    uc = GetUserUseCase()
    with pytest.raises(EntityNotFoundError):
        await uc.execute(uuid4(), active_tenant.id, uow)


@pytest.mark.asyncio
async def test_get_user_happy_path(uow: FakeUnitOfWork, active_tenant: Tenant) -> None:
    """GetUserUseCase returns user when found."""
    create_uc = CreateUserUseCase()
    user = await create_uc.execute(CreateUserCommand(tenant_id=active_tenant.id, email="charlie@acme.com"), uow)

    get_uc = GetUserUseCase()
    fetched = await get_uc.execute(user.id, active_tenant.id, uow)
    assert fetched.email == "charlie@acme.com"
