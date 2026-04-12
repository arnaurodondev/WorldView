"""User entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.enums import TenantUserRole, UserStatus

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass
class User:
    tenant_id: UUID
    email: str
    id: UUID = field(default_factory=new_uuid)
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime = field(default_factory=utc_now)
    external_id: str | None = None
    role: TenantUserRole = TenantUserRole.OWNER

    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE
