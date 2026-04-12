"""Invitation entity — schema stub for B2B invite flow (PRD-0025 §5)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.enums import TenantUserRole

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


def _default_token() -> str:
    """Generate a 43-character base64url token (32 random bytes)."""
    return secrets.token_urlsafe(32)


@dataclass
class Invitation:
    """Pending invitation for a user to join a tenant.

    Schema stub only — no use cases or endpoints in this PRD.
    The Alembic migration creates the ``invitations`` table.
    """

    tenant_id: UUID
    email: str
    role: TenantUserRole
    expires_at: datetime  # UTC-aware; must be > created_at
    id: UUID = field(default_factory=new_uuid)
    token: str = field(default_factory=_default_token)
    accepted_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.role == TenantUserRole.OWNER:
            raise ValueError("Invitation role cannot be OWNER; use ADMIN or MEMBER only.")
