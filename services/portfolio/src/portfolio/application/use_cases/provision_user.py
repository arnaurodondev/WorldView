"""ProvisionUserUseCase — idempotent user provisioning via Zitadel OIDC sub.

Called by the S9 API Gateway's callback handler immediately after a user authenticates
via Zitadel for the first time, or on every auth callback to ensure the user exists.

Implements PRD-0025 §3.3 (F-14..F-19) and §6.7 (data flow A steps 17-22).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from portfolio.application.use_cases.ensure_root_portfolio import EnsureRootPortfolioUseCase
from portfolio.domain.entities.tenant import Tenant
from portfolio.domain.entities.user import User
from portfolio.domain.enums import AuthAuditEventType, TenantUserRole
from portfolio.domain.errors import ProvisionConflictError
from portfolio.domain.value_objects import AuthAuditEvent

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class ProvisionResult:
    """Result of a successful provision call."""

    user_id: UUID
    tenant_id: UUID
    email: str
    created: bool  # True if a new tenant+user were created
    linked: bool  # True if an existing user was linked to the OIDC sub


class ProvisionUserUseCase:
    """Idempotent user provisioning from Zitadel OIDC ``sub``.

    The use case is safe to call on every OIDC callback — subsequent calls with
    the same ``sub`` return the existing user without any DB writes.

    Step logic (PRD-0025 §3.3):
      1. Lookup by ``sub`` → return existing user (idempotent fast-path)
      2. Lookup by ``email`` with NULL ``external_id`` → link + audit
      3. Lookup by ``email`` with DIFFERENT ``external_id`` → 409 conflict
      4. Neither found → create new tenant + user atomically
    """

    async def execute(
        self,
        sub: str,
        email: str,
        username: str | None,
        uow: UnitOfWork,
    ) -> ProvisionResult:
        # Step 1: fast-path idempotency — sub already exists
        existing = await uow.users.find_by_external_id(sub)
        if existing is not None:
            return ProvisionResult(
                user_id=existing.id,
                tenant_id=existing.tenant_id,
                email=existing.email,
                created=False,
                linked=False,
            )

        # Step 2: email exists with NULL external_id → link
        unlinked = await uow.users.find_by_email_without_external_id(email)
        if unlinked is not None:
            await uow.users.link_external_id(unlinked.id, sub)
            audit = AuthAuditEvent(
                event_type=AuthAuditEventType.ACCOUNT_LINKED,
                sub=sub,
                user_id=unlinked.id,
                email=email,
                detail={"linked_user_id": str(unlinked.id)},
            )
            await uow.auth_audit_log.create(audit, unlinked.id)
            # PLAN-0046 Wave 3 / T-46-3-02: ensure the linked user has a ROOT
            # portfolio. Pre-OIDC users that existed before PRD-0046 may not
            # have one yet — calling EnsureRootPortfolioUseCase here makes
            # link-on-login the natural backfill trigger for active users.
            # Idempotent: returns existing root if already provisioned.
            await EnsureRootPortfolioUseCase().execute(unlinked.id, unlinked.tenant_id, uow)
            await uow.commit()
            return ProvisionResult(
                user_id=unlinked.id,
                tenant_id=unlinked.tenant_id,
                email=unlinked.email,
                created=False,
                linked=True,
            )

        # Step 3: same email already linked to a DIFFERENT sub → 409 conflict
        conflict_user = await uow.users.find_by_email_with_conflicting_external_id(email, sub)
        if conflict_user is not None:
            audit = AuthAuditEvent(
                event_type=AuthAuditEventType.PROVISION_CONFLICT_409,
                sub=sub,
                user_id=conflict_user.id,
                email=email,
                detail={"conflict_sub": conflict_user.external_id or ""},
            )
            await uow.auth_audit_log.create(audit, conflict_user.id)
            await uow.commit()
            raise ProvisionConflictError(email=email, conflict_sub=conflict_user.external_id)

        # Step 4: brand-new user — create tenant + user atomically
        tenant_name = username or email.split("@", maxsplit=1)[0]
        tenant = Tenant(name=tenant_name)
        await uow.tenants.save(tenant)

        user = User(
            tenant_id=tenant.id,
            email=email,
            external_id=sub,
            role=TenantUserRole.OWNER,
        )
        await uow.users.save(user)
        # Flush to ensure the user row is visible within the transaction before
        # the audit log FK references it (ORM lacks a relationship() to auto-order).
        await uow.flush()

        audit = AuthAuditEvent(
            event_type=AuthAuditEventType.USER_CREATED,
            sub=sub,
            user_id=user.id,
            email=email,
            detail={},
        )
        await uow.auth_audit_log.create(audit, user.id)

        # PLAN-0046 Wave 3 / T-46-3-02: every brand-new user gets a ROOT
        # portfolio in the same commit so the user exits provisioning with
        # an immediately-usable "All Accounts" view. Failure to create the
        # root here would surface as a regular DB error and roll back the
        # entire user-creation atomically — preferable to a half-provisioned
        # user with no root portfolio.
        await EnsureRootPortfolioUseCase().execute(user.id, tenant.id, uow)
        await uow.commit()

        return ProvisionResult(
            user_id=user.id,
            tenant_id=tenant.id,
            email=email,
            created=True,
            linked=False,
        )
