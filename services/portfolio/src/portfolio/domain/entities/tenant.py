"""Tenant entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.enums import TenantStatus

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass
class Tenant:
    name: str
    id: UUID = field(default_factory=new_uuid)
    status: TenantStatus = TenantStatus.ACTIVE
    created_at: datetime = field(default_factory=utc_now)

    def is_active(self) -> bool:
        return self.status == TenantStatus.ACTIVE
