"""Unit tests for ProvisionUserUseCase (PRD-0025 §3.3, T-C-1-04)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from portfolio.application.use_cases.provision_user import ProvisionUserUseCase
from portfolio.domain.entities.user import User
from portfolio.domain.enums import AuthAuditEventType, TenantUserRole, UserStatus
from portfolio.domain.errors import ProvisionConflictError

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

TENANT_ID = uuid4()


# ── T-C-1-04-01: Brand-new user ───────────────────────────────────────────────


async def test_provision_creates_user_and_tenant() -> None:
    """New sub → tenant + user created atomically; created=True, linked=False."""
    uow = FakeUnitOfWork()
    uc = ProvisionUserUseCase()

    result = await uc.execute(sub="sub-001", email="alice@example.com", username="alice", uow=uow)

    assert result.created is True
    assert result.linked is False
    assert result.email == "alice@example.com"

    # User persisted
    users = list(uow._users._store.values())
    assert len(users) == 1
    assert users[0].external_id == "sub-001"
    assert users[0].email == "alice@example.com"
    assert users[0].role == TenantUserRole.OWNER

    # Tenant persisted with username as name
    tenants = list(uow._tenants._store.values())
    assert len(tenants) == 1
    assert tenants[0].name == "alice"

    # UoW committed
    assert uow.committed is True


async def test_provision_creates_tenant_with_email_prefix_when_no_username() -> None:
    """New sub without username → tenant name derived from email prefix."""
    uow = FakeUnitOfWork()
    uc = ProvisionUserUseCase()

    result = await uc.execute(sub="sub-002", email="bob@example.com", username=None, uow=uow)

    assert result.created is True
    tenants = list(uow._tenants._store.values())
    assert tenants[0].name == "bob"  # email split on @


# ── T-C-1-04-02: Idempotency ─────────────────────────────────────────────────


async def test_provision_idempotent_same_sub() -> None:
    """Same sub called twice → same user_id returned; created=False, no extra writes."""
    uow = FakeUnitOfWork()
    uc = ProvisionUserUseCase()

    result1 = await uc.execute(sub="sub-idem", email="carol@example.com", username=None, uow=uow)
    commit_count_after_first = uow.commit_count

    result2 = await uc.execute(sub="sub-idem", email="carol@example.com", username=None, uow=uow)

    assert result1.user_id == result2.user_id
    assert result2.created is False
    assert result2.linked is False
    # No additional commit on the second call
    assert uow.commit_count == commit_count_after_first


# ── T-C-1-04-03: Link existing user ──────────────────────────────────────────


async def test_provision_links_by_email() -> None:
    """Existing user with NULL external_id → linked=True; external_id updated."""
    uow = FakeUnitOfWork()
    existing_user = User(
        id=uuid4(),
        tenant_id=TENANT_ID,
        email="dave@example.com",
        status=UserStatus.ACTIVE,
        external_id=None,  # no OIDC sub yet
    )
    uow.seed_user(existing_user)

    uc = ProvisionUserUseCase()
    result = await uc.execute(sub="sub-link", email="dave@example.com", username=None, uow=uow)

    assert result.linked is True
    assert result.created is False
    assert result.user_id == existing_user.id

    # external_id updated in store
    updated_user = uow._users._store[existing_user.id]
    assert updated_user.external_id == "sub-link"

    # No new tenant created
    assert len(uow._tenants._store) == 0


# ── T-C-1-04-04: Conflict → 409 ──────────────────────────────────────────────


async def test_provision_409_on_conflict() -> None:
    """Same email already linked to a DIFFERENT sub → ProvisionConflictError."""
    uow = FakeUnitOfWork()
    conflicting_user = User(
        id=uuid4(),
        tenant_id=TENANT_ID,
        email="eve@example.com",
        status=UserStatus.ACTIVE,
        external_id="sub-original",  # already linked to a different sub
    )
    uow.seed_user(conflicting_user)

    uc = ProvisionUserUseCase()
    with pytest.raises(ProvisionConflictError) as exc_info:
        await uc.execute(sub="sub-attacker", email="eve@example.com", username=None, uow=uow)

    err = exc_info.value
    assert err.email == "eve@example.com"
    assert err.conflict_sub == "sub-original"
    assert err.error_code == "PROVISION_CONFLICT"


# ── T-C-1-04-05: Audit log on create ─────────────────────────────────────────


async def test_provision_writes_audit_log_on_create() -> None:
    """New user provision → USER_CREATED event in auth_audit_log."""
    uow = FakeUnitOfWork()
    uc = ProvisionUserUseCase()

    result = await uc.execute(sub="sub-audit-create", email="frank@example.com", username=None, uow=uow)

    events = uow.auth_audit_log.events_by_type(AuthAuditEventType.USER_CREATED)
    assert len(events) == 1
    event, user_id = events[0]
    assert event.sub == "sub-audit-create"
    assert event.email == "frank@example.com"
    assert user_id == result.user_id


# ── T-C-1-04-06: Audit log on link ───────────────────────────────────────────


async def test_provision_writes_audit_log_on_link() -> None:
    """Email-link provision → ACCOUNT_LINKED event in auth_audit_log."""
    uow = FakeUnitOfWork()
    existing_user = User(
        id=uuid4(),
        tenant_id=TENANT_ID,
        email="grace@example.com",
        status=UserStatus.ACTIVE,
        external_id=None,
    )
    uow.seed_user(existing_user)

    uc = ProvisionUserUseCase()
    await uc.execute(sub="sub-link-audit", email="grace@example.com", username=None, uow=uow)

    events = uow.auth_audit_log.events_by_type(AuthAuditEventType.ACCOUNT_LINKED)
    assert len(events) == 1
    event, user_id = events[0]
    assert event.sub == "sub-link-audit"
    assert user_id == existing_user.id


async def test_provision_writes_audit_log_on_conflict() -> None:
    """Conflict provision → PROVISION_CONFLICT_409 event logged before raising."""
    uow = FakeUnitOfWork()
    conflicting_user = User(
        id=uuid4(),
        tenant_id=TENANT_ID,
        email="hank@example.com",
        status=UserStatus.ACTIVE,
        external_id="sub-taken",
    )
    uow.seed_user(conflicting_user)

    uc = ProvisionUserUseCase()
    with pytest.raises(ProvisionConflictError):
        await uc.execute(sub="sub-new", email="hank@example.com", username=None, uow=uow)

    events = uow.auth_audit_log.events_by_type(AuthAuditEventType.PROVISION_CONFLICT_409)
    assert len(events) == 1
