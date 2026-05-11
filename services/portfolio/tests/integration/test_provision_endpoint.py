"""Integration tests for ProvisionUserUseCase against real Postgres (T-C-1-06).

Tests verify DB-level atomicity, idempotency, and link behavior.
Uses testcontainers (same pattern as existing integration tests).
"""

from __future__ import annotations

import asyncio

import pytest
from portfolio.application.use_cases.provision_user import ProvisionUserUseCase
from portfolio.domain.enums import AuthAuditEventType
from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ── T-C-1-06-01: New user transaction ─────────────────────────────────────────


async def test_provision_new_user_transaction(integration_session_factory) -> None:
    """tenant + user + auth_audit_log all written in a single transaction; all 3 rows exist."""
    session_factory, engine = integration_session_factory
    uc = ProvisionUserUseCase()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        result = await uc.execute(
            sub="sub-int-001",
            email="integration-new@example.com",
            username="intuser",
            uow=uow,
        )

    assert result.created is True
    assert result.linked is False

    # Verify all 3 rows exist in Postgres
    async with session_factory() as session:
        # User row
        user_row = await session.execute(
            text("SELECT id, external_id, role FROM users WHERE email = :email"),
            {"email": "integration-new@example.com"},
        )
        user = user_row.fetchone()
        assert user is not None
        assert str(user.id) == str(result.user_id)
        assert user.external_id == "sub-int-001"
        assert user.role == "owner"

        # Tenant row
        tenant_row = await session.execute(
            text("SELECT id FROM tenants WHERE id = :tid"),
            {"tid": str(result.tenant_id)},
        )
        assert tenant_row.fetchone() is not None

        # Audit log row
        audit_row = await session.execute(
            text("SELECT event_type, sub FROM auth_audit_log WHERE sub = :sub"),
            {"sub": "sub-int-001"},
        )
        audit = audit_row.fetchone()
        assert audit is not None
        assert audit.event_type == AuthAuditEventType.USER_CREATED.value

    await engine.dispose()


# ── T-C-1-06-02: Link existing user (atomic) ──────────────────────────────────


async def test_provision_links_existing_atomic(integration_session_factory) -> None:
    """UPDATE external_id + auth_audit_log written atomically; user_id unchanged."""
    session_factory, engine = integration_session_factory
    uc = ProvisionUserUseCase()

    # First provision: creates user without sub (simulate pre-existing user)
    # We create the user directly via the repo
    from uuid import uuid4

    from portfolio.domain.entities.tenant import Tenant
    from portfolio.domain.entities.user import User
    from portfolio.domain.enums import TenantStatus, UserStatus

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        tenant = Tenant(name="Link Corp", status=TenantStatus.ACTIVE)
        await uow.tenants.save(tenant)
        user = User(
            id=uuid4(),
            tenant_id=tenant.id,
            email="link-test@example.com",
            status=UserStatus.ACTIVE,
            external_id=None,
        )
        await uow.users.save(user)
        await uow.commit()

    original_user_id = user.id

    # Provision via OIDC sub → should link
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        result = await uc.execute(
            sub="sub-link-int",
            email="link-test@example.com",
            username=None,
            uow=uow,
        )

    assert result.linked is True
    assert result.user_id == original_user_id
    assert result.created is False

    # Verify DB state
    async with session_factory() as session:
        user_row = await session.execute(
            text("SELECT external_id FROM users WHERE id = :uid"),
            {"uid": str(original_user_id)},
        )
        row = user_row.fetchone()
        assert row is not None
        assert row.external_id == "sub-link-int"

        audit_row = await session.execute(
            text("SELECT event_type FROM auth_audit_log WHERE sub = :sub"),
            {"sub": "sub-link-int"},
        )
        audit = audit_row.fetchone()
        assert audit is not None
        assert audit.event_type == AuthAuditEventType.ACCOUNT_LINKED.value

    await engine.dispose()


# ── T-C-1-06-03: Idempotency (sequential) ────────────────────────────────────


async def test_provision_idempotent_db(integration_session_factory) -> None:
    """Two sequential calls for same sub → same user_id returned; only 1 user row in DB."""
    session_factory, engine = integration_session_factory
    uc = ProvisionUserUseCase()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        result1 = await uc.execute(
            sub="sub-idem-db",
            email="idem-db@example.com",
            username=None,
            uow=uow,
        )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        result2 = await uc.execute(
            sub="sub-idem-db",
            email="idem-db@example.com",
            username=None,
            uow=uow,
        )

    assert result1.user_id == result2.user_id
    assert result2.created is False

    # Exactly 1 user row with this sub
    async with session_factory() as session:
        count_row = await session.execute(
            text("SELECT COUNT(*) FROM users WHERE external_id = :sub"),
            {"sub": "sub-idem-db"},
        )
        assert count_row.scalar() == 1

    await engine.dispose()


# ── T-C-1-06-04: Concurrent same sub ─────────────────────────────────────────


async def test_provision_concurrent_same_sub(integration_session_factory) -> None:
    """Two concurrent calls for same sub → exactly one user created (dedup via external_id unique index)."""
    session_factory, engine = integration_session_factory
    uc = ProvisionUserUseCase()

    async def _provision() -> None:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            try:
                await uc.execute(
                    sub="sub-concurrent",
                    email="concurrent@example.com",
                    username=None,
                    uow=uow,
                )
            except Exception:  # noqa: S110
                pass  # concurrent UniqueViolation is expected; second call is silently dropped

    # Run two provisions concurrently
    await asyncio.gather(_provision(), _provision())

    # Exactly 1 user row with this sub (unique index enforced at DB level)
    async with session_factory() as session:
        count_row = await session.execute(
            text("SELECT COUNT(*) FROM users WHERE external_id = :sub"),
            {"sub": "sub-concurrent"},
        )
        count = count_row.scalar()
        assert count == 1

    await engine.dispose()
